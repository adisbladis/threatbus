import broker
from contextlib import suppress
import re
from stix2 import EqualityComparisonExpression, Indicator, Sighting
from stix2patterns.v21.pattern import Pattern
from threatbus.data import (
    Operation,
    Subscription,
    ThreatBusSTIX2Constants,
    Unsubscription,
)
from typing import Union

# See the documentation for the Zeek INTEL framework [1] and STIX-2 cyber
# observable objects [2]
# [1] https://docs.zeek.org/en/stable/scripts/base/frameworks/intel/main.zeek.html#type-Intel::Type
# [2] https://docs.oasis-open.org/cti/stix/v2.1/cs01/stix-v2.1-cs01.html#_mlbmudhl16lr
zeek_intel_type_map = {
    "domain-name:value": "DOMAIN",
    "email-addr:value": "EMAIL",
    "file:name": "FILE_NAME",
    "file:hashes.MD5": "FILE_HASH",
    "file:hashes.'SHA-1'": "FILE_HASH",
    "file:hashes.'SHA-256'": "FILE_HASH",
    "file:hashes.'SHA-512'": "FILE_HASH",
    "file:hashes.'SHA3-256'": "FILE_HASH",
    "file:hashes.'SHA3-512'": "FILE_HASH",
    "file:hashes.SSDEEP": "FILE_HASH",
    "file:hashes.TLSH": "FILE_HASH",
    "ipv4-addr:value": "ADDR",
    "ipv6-addr:value": "ADDR",
    "software:name": "SOFTWARE",
    "url:value": "URL",
    "user:user_id": "USER_NAME",
    "user:account_login": "USER_NAME",
    "x509-certificate:hashes.'SHA-1'": "CERT_HASH",  # Zeek only supports SHA-1
}


def map_management_message(
    broker_data, module_namespace: str
) -> Union[Subscription, Unsubscription, None]:
    """
    Maps a management message to an actionable instruction for Threat Bus.
    @param broker_data The raw data that was received via broker
    @param module_namespace A Zeek namespace to accept events from
    @return A Subscription/Unsubscription object or None in case there is no
    valid mapping.
    """
    event = broker.zeek.Event(broker_data)
    name, args = event.name(), event.args()
    module_namespace = module_namespace + "::" if module_namespace else ""
    name = name[name.startswith(module_namespace) and len(module_namespace) :]
    if name == "subscribe" and len(args) == 2:
        (topic, snapshot_delta) = args
        if topic:
            return Subscription(topic, snapshot_delta)
    elif name == "unsubscribe" and len(args) == 1:
        topic = args[0]
        if topic:
            return Unsubscription(topic)
    return None


def map_broker_event_to_sighting(broker_data, module_namespace, logger):
    """
    Maps a Broker message, based on the event name, to a STIX-2 indicator or
    STIX-2 Sighting.
    @param broker_data The raw data that was received via broker
    @param module_namespace A Zeek namespace to accept events from
    """
    event = broker.zeek.Event(broker_data)
    name, args = event.name(), event.args()
    module_namespace = module_namespace + "::" if module_namespace else ""
    name = name[name.startswith(module_namespace) and len(module_namespace) :]
    if name != "sighting" or len(args) != 3:
        if logger:
            logger.debug(f"Discarding Broker event with unknown type: {name}")
        return None
    # convert args to STIX-2 sighting
    (timestamp, ioc_id, context) = args
    return Sighting(
        created=timestamp,
        sighting_of_ref=str(ioc_id),
        custom_properties={
            ThreatBusSTIX2Constants.X_THREATBUS_SIGHTING_CONTEXT.value: context
        },
    )


def is_point_equality_ioc(pattern_str: str) -> bool:
    """
    Predicate to check if a STIX-2 pattern is a point-IoC, i.e., if the pattern
    only consists of a single EqualityComparisonExpression
    @param pattern_str The STIX-2 pattern string to inspect
    """
    pattern = Pattern(pattern_str)
    # InspectionListener https://github.com/oasis-open/cti-pattern-validator/blob/e926d0a14adf88de08acb908a51db1f453c13647/stix2patterns/v21/inspector.py#L5
    # E.g.,   pattern = "[domain-name:value = 'evil.com']"
    # =>           il = pattern_data(comparisons={'domain-name': [(['value'], '=', "'evil.com'")]}, observation_ops=set(), qualifiers=set())
    # =>  cybox_types = ['domain-name']
    il = pattern.inspect()
    cybox_types = list(il.comparisons.keys())
    return (
        len(il.observation_ops) == 0
        and len(il.qualifiers) == 0
        and len(il.comparisons) == 1
        and len(cybox_types) == 1  # must be point-indicator (one field only)
        and len(il.comparisons[cybox_types[0]][0]) == 3  # ('value', '=', 'evil.com')
        and il.comparisons[cybox_types[0]][0][1] == "="  # equality comparison
    )


def map_indicator_to_broker_event(
    indicator: Indicator, module_namespace: str, logger
) -> Union[broker.zeek.Event, None]:
    """
    Maps STIX-2 Indicators to Broker events using the Zeek Intel format
    @see https://docs.zeek.org/en/current/scripts/base/frameworks/intel/main.zeek.html#type-Intel::Type
    @param indicator The STIX-2 Indicator to convert
    @param module_namespace A Zeek namespace to use for sending the event
    @return The mapped broker event or None
    """
    if type(indicator) is not Indicator:
        if logger:
            logger.debug(f"Discarding message, expected STIX-2 Indicator: {indicator}")
        return None

    if not is_point_equality_ioc(indicator.pattern):
        logger.debug(
            f"Zeek only supports point-IoCs. Cannot map compound pattern to a Zeek Intel item: {indicator.pattern}"
        )
        return None

    # pattern is in the form [file:name = 'foo']
    (object_path, ioc_value) = indicator.pattern[1:-1].split("=")
    object_path, ioc_value = object_path.strip(), ioc_value.strip()
    if ioc_value.startswith("'") and ioc_value.endswith("'"):
        ioc_value = ioc_value[1:-1]

    # get matching Zeek intel type
    zeek_type = zeek_intel_type_map.get(object_path, None)
    if not zeek_type:
        logger.debug(
            f"No matching Zeek type found for STIX-2 indicator type '{object_path}'"
        )
        return None

    if zeek_type == "URL":
        # remove leading protocol, if any
        ioc_value = re.sub(r"^https?://", "", ioc_value)
    elif zeek_type == "ADDR" and re.match(".+/.+", ioc_value):
        # elevate to subnet if possible
        zeek_type = "SUBNET"

    operation = "ADD"  ## Zeek operation to add a new Intel item
    if (
        ThreatBusSTIX2Constants.X_THREATBUS_UPDATE.value
        in indicator.object_properties()
        and indicator.x_threatbus_update == Operation.REMOVE.value
    ):
        operation = "REMOVE"
    return broker.zeek.Event(
        f"{module_namespace}::intel",
        (indicator.created, str(indicator.id), zeek_type, ioc_value, operation),
    )
