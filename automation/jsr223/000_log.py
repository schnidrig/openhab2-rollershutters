
# copied from https://raw.githubusercontent.com/steve-bate/openhab2-jython/5cf5b09d1f6d492358207fde5ad14f4e7a2689b9/lib/openhab/log.py
# and slightly modified.

# this script is not needed if you already use the library by Steve Bate: https://github.com/steve-bate/openhab2-jython/tree/master

import logging
from org.slf4j import Logger, LoggerFactory

class Slf4jHandler(logging.Handler):
    def emit(self, record):
        message = self.format(record)
        logger_name = record.name
        if record.name == "root":
            logger_name = Logger.ROOT_LOGGER_NAME
        logger = LoggerFactory.getLogger(logger_name)
        level = record.levelno
        if level == logging.DEBUG:
            logger.debug(message)
        elif level == logging.INFO:
            logger.info(message)
        elif level == logging.WARN:
            logger.warn(message)
        elif level in [logging.ERROR, logging.CRITICAL] :
            logger.error(message)
            
def scriptLoaded(id):
    handler = Slf4jHandler()
    logging.root.setLevel(logging.DEBUG)
    logging.root.handlers = [handler]

def scriptUnloaded():
    logging.root.handlers = []
