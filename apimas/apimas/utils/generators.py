from cStringIO import StringIO
from datetime import datetime
import os
import random
from urlparse import urljoin
import zipfile
from faker import Factory
from pytz import timezone as py_timezone
from apimas import documents as doc
from apimas.decorators import after


fake = Factory.create()


def generate_integer(upper=10, lower=0):
    return random.randint(lower, upper)


def generate_float(upper=10, lower=0):
    return random.uniform(lower, upper)


def generate_string(max_length=255):
    size = random.randint(1, max_length)
    return fake.pystr(max_chars=size)


generate_email = fake.email


def generate_choices(choices=None):
    return random.choice(choices or [])


def generate_boolean():
    return random.choice([True, False])


class DateGenerator(object):
    """
    Date generator.

    Args:
        native (bool): `True` if a python date object is generated; `False`
            otherwise.
    """
    DEFAULT_FORMATS = ['%Y-%m-%d']

    def __init__(self, native):
        self.native = native

    def __call__(self, date_formats=None):
        """
        Generates a random python date object or a string representing a date
        based on the allowed date formats.

        Args:
            date_formats (list): (optional) List of allowed string formats
                which are used to represent date.
        """
        date_obj = fake.date_object()
        if self.native:
            return date_obj
        date_formats = date_formats or self.DEFAULT_FORMATS
        return datetime.strftime(date_obj, random.choice(date_formats))
        return date_obj


class DateTimeGenerator(DateGenerator):
    DEFAULT_FORMATS = ['%Y-%m-%dT%H:%M:%S']

    def __call__(self, date_formats=None, timezone='UTC'):
        """
        Generates a random python datetime object or a string representing a
        datetime based on the allowed date formats and the timezone.

        Args:
            date_formats (list): (optional) List of allowed string formats
                which are used to represent date.
            timezone (str): (optional) Timezone info.
        """
        tzinfo = None
        if timezone:
            tzinfo = py_timezone(fake.timezone()) if timezone is True\
                else py_timezone(timezone)
        date_obj = fake.date_time(tzinfo=tzinfo)
        if self.native:
            return date_obj
        date_formats = date_formats or self.DEFAULT_FORMATS
        return datetime.strftime(date_obj, random.choice(date_formats))
        return date_obj


def generate_fake_file(file_name=None, size=8, archived=False):
    """
    Generates a file-like object using `cStringIO` library.

    Args:
        file_name (str): (optional) Name of the mock file. If `None` a
            random name is generated.
        size (int):  (optional) Size of the generated file in bytes.
        archived (bool): `True` if generated file should be archived.
    """
    content = os.urandom(size)
    buff = StringIO()
    buff.write(content)
    file_name = file_name or fake.file_name()
    if not archived:
        return buff
    with zipfile.ZipFile(buff, mode='w',
                         compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(file_name, buff.getvalue())
    return buff


def generate_ref(to):
    random_pk = random.randint(1, 10)
    ref = to.strip('/') + '/'
    return urljoin(ref, str(random_pk) + '/')


class RequestGenerator(object):
    """
    Generator of random Request data.

    It reads from specification to construct the appropriate generators and
    field names.

    Args:
        spec (dict): Specification of a collection.

    Examples:
        >>> SPEC = {
        ...     '*': {
        ...         'foo': {
        ...             '.string': {}
        ...         },
        ...         'bar': {
        ...             '.integer': {}
        ...         },
        ...         'ignored': {
        ...             '.integer': {},
        ...             '.readonly': {},
        ...         }
        ...     }
        ... }
        >>> from apimas.utils.generators import RequestGenerator
        >>> generator = RequestGenerator(SPEC)
        >>> generator.construct()
        {'bar': 7, 'foo': u'PtkvOypcrcxaWfqouPWVbxFZzvaHMJrVSlJ'}
    """

    RANDOM_GENERATORS = {
        '.string': generate_string,
        '.text': generate_string,
        '.email': generate_email,
        '.integer': generate_integer,
        '.float': generate_float,
        '.datetime': DateTimeGenerator(native=False),
        '.date': DateGenerator(native=False),
        '.boolean': generate_boolean,
        '.file': generate_fake_file,
        '.choices': generate_choices,
        '.ref': generate_ref,
    }

    COMMON_FIELDS = {
        '.string',
        '.text',
        '.email',
        '.integer',
        '.float',
        '.datetime',
        '.date',
        '.boolean',
        '.file',
        '.choices',
        '.ref',
    }

    _SKIP = object()

    def __init__(self, spec):
        self.spec = spec.get('*')
        self._constructors = {
            'struct': self._struct,
            'readonly': self._readonly,
            'array of': self._array_of,
            'serial': self._serial,
            'default': self._default
        }
        self._constructors.update(
            {k[1:]: self._common_constructor(k) for k in self.COMMON_FIELDS})

    def _default(self, context):
        return context.instance

    def _common_constructor(self, field_type):
        @after(['.readonly'])
        def generate(context):
            if context.instance is self._SKIP:
                return None
            return self.RANDOM_GENERATORS[field_type](**context.spec)
        return generate

    @after(['.readonly'])
    def _serial(self, context):
        return None

    def _readonly(self, context):
        return self._SKIP

    def _compound(self, instance, spec):
        if instance is self._SKIP:
            return None
        assert spec is not None
        return spec

    @after(['.readonly'])
    def _struct(self, context):
        return self._compound(context.instance, context.spec)

    @after(['.readonly'])
    def _array_of(self, context):
        return [self._compound(context.instance, context.spec)]

    def construct(self):
        """
        Generates random data based on specification.

        Returns:
            dict: A dictionary of random data per field.
        """
        instance = doc.doc_construct(
            {}, self.spec, constructors=self._constructors,
            allow_constructor_input=False, autoconstruct='default',
            construct_spec=True)
        return instance
