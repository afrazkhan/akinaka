from datetime import timedelta, timezone, datetime
from time import strftime

# Take a duration in seconds and work out the datetime value for the datetime at that date and time ago
def datetime_this_seconds_ago(duration):
  return (datetime.now(timezone.utc) + timedelta(seconds=-duration))

def seconds_from_hours(hours):
  return (60*60)*hours
