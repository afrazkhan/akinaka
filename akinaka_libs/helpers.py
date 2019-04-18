from datetime import timedelta, timezone, datetime
from time import strftime
import pprint
import logging

# Take a duration in seconds and work out the datetime value for the datetime at that date and time ago
def datetime_this_seconds_ago(duration):
  return (datetime.now(timezone.utc) + timedelta(seconds=-duration))

def seconds_from_hours(hours):
  return (60*60)*hours

def log(message):
  print(message)

def set_logger():
  return logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S%z')
