import threading
from collections import defaultdict
import time
import threatbus

"""In-Memory backbone plugin for Threat Bus"""

plugin_name = "inmem"

subscriptions = defaultdict(set)
lock = threading.Lock()


def validate_config(config):
    return True


def provision(logger, inq):
    """Provisions all messages that arrive on the inq to all subscribers of that topic.
        @param logger A logging.logger object
        @param inq The in-Queue to read messages from
    """
    global subscriptions, lock
    while True:
        msg = inq.get(block=True)
        logger.debug(f"Backbone got message {msg}")
        topic = f"tenzir/threatbus/{type(msg).__name__.lower()}"
        lock.acquire()
        for t in filter(lambda t: str(topic).startswith(str(t)), subscriptions.keys()):
            for outq in subscriptions[t]:
                outq.put(msg)
        lock.release()


@threatbus.backbone
def subscribe(topics, q):
    global subscriptions, lock
    lock.acquire()
    for topic in topics:
        subscriptions[topic].add(q)
    lock.release()


@threatbus.backbone
def unsubscribe(topics, q):
    global subscriptions, lock
    lock.acquire()
    for topic in topics:
        if q in subscriptions[topic]:
            subscriptions[topic].remove(q)
    lock.release()


@threatbus.backbone
def run(config, logging, inq):
    global logger
    logger = threatbus.logger.setup(logging, __name__)
    config = config[plugin_name]
    try:
        validate_config(config)
    except Exception as e:
        raise ValueError("Invalid config for plugin {}: {}".format(plugin_name, str(e)))
    threading.Thread(target=provision, args=(logger, inq), daemon=True).start()
    logger.info("In-memory backbone started.")