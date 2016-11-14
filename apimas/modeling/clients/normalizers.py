from datetime import datetime, date
from requests.compat import urljoin


class RefNormalizer(object):
    """
    Normalizer of a value that implies an id of a referenced collection.

    It constructs the URL location where the referenced resource specified
    by the given id is located.
    """
    def __init__(self, ref_endpoint):
        self.ref_endpoint = ref_endpoint

    def __call__(self, value):
        if value is None:
            return value
        return urljoin(self.ref_endpoint, value) + '/'


class DateTimeNormalizer(object):
    """
    Normalize a datetime object to a string value based on the given format.

    If value is string, then it is checked if it follows the given format.
    """
    DEFAULT_FORMAT = '%Y-%m-%dT%H:%M:%S'

    def __init__(self, date_format=None):
        self.date_format = date_format or self.DEFAULT_FORMAT

    def __call__(self, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time())
            return value.strftime(self.date_format)
        elif isinstance(value, datetime):
            return value.strftime(self.date_format)
        elif isinstance(value, str):
            datetime.strptime(value, self.date_format)
        return value


class DateNormalizer(DateTimeNormalizer):
    DEFAULT_FORMAT = '%Y-%m-%d'