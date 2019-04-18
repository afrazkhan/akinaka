from akinaka_libs import helpers
import logging

helpers.set_logger()

class AkinakaGeneralError(Exception):
    pass

class AkinakaUpdateError(Exception):
    pass

class AkinakaLoggingError(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        logging.error(message)

class AkinakaCriticalException(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        logging.error(message)
        
        exit(1)