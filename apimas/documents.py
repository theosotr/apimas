"""A generic recursive object-document manipulation toolkit.
"""
from inspect import getargspec
from bisect import bisect_right
from errors import ValidationError, NotFound, InvalidInput, ConflictError


bytes = str


class DeferConstructor(Exception):
    """An exception raised by constructors to defer their execution."""


def doc_locate(doc, path):
    """Walk a path down a document.

    The path is a list of str segments. Starting from the root node, a cursor
    points at the first segment. At each node, the segment under the cursor is
    used to access the node to go deeper. As the cursor moves from the begining
    towards the end of the path segment list, the list is logically split into
    two parts. The first part, the trail, is the prefix of segments that have
    already been used in descending through the document hierarchy and
    corresponds to the current path. The second part of the path, the feed, is
    the suffix of segments that have not yet been accessed to descend to the
    full path.

    There are two outcomes:
        1. feed is empty, meaning that the given path was found
        2. feed is non-empty, meaning that the first segment in the feed was
           not found in the document at the path formed by trail.

    Args:
        doc (dict):
            A recursive object-document
        path (tuple):
            A sequence of path segments as in ('path', 'to', 'somewhere')

    Returns:
        tuple of lists:
            feed (list):
                List of path segments left that have not yet been accessed
            trail (list):
                List of path segments already accessed. It corresponds to the
                current path of the node where no further descent was possible
                and thus doc_locate() was terminated.
            nodes (list):
                List of nodes already accessed, in order.
    """
    feed = list(reversed(path))
    trail = []
    nodes = [doc]
    while feed:
        segment = feed.pop()
        if not segment:
            continue

        if not isinstance(doc, dict) or segment not in doc:
            feed.append(segment)
            break

        trail.append(segment)
        doc = doc[segment]
        nodes.append(doc)

    return feed, trail, nodes


def doc_set(doc, path, value):
    if not path:
        m = "Cannot set root document at empty path."
        raise InvalidInput(m)

    feed, trail, nodes = doc_locate(doc, path)

    doc = nodes[-1]
    if feed and isinstance(doc, dict):
        # path was not found and parent points to a sub-doc
        doc = nodes[-1]
        while True:
            segment = feed.pop()
            if not feed:
                break
            new_doc = {}
            doc[segment] = new_doc
            doc = new_doc

        doc[segment] = value
        old_value = None

    else:
        # path was found or stopped in a scalar value, we have to replace the
        # last node
        parent = nodes[-2]
        segment = trail[-1]
        old_value = parent[segment]
        parent[segment] = value

    return old_value


def doc_get(doc, path):
    feed, trail, nodes = doc_locate(doc, path)
    return None if feed else nodes[-1]


def doc_iter(doc, preorder=False, postorder=True, path=()):
    """Iterate the document hierarchy yielding each path and node.

    Args:
        doc (dict):
            A hierarchical object-document
        preorder (bool):
            If true, yield path and node at the first node visit.
            False by default.
        postorder (bool):
            If true, yield path and node at the second node visit.
            True by default.

            Note that postorder is an independent from preorder.
            If both are true, nodes will be yielded two times.
            If none is true, doc is iterated for any possible side-effects,
            but nothing is yielded.
        path (tuple):
            A prefix path to append in yielded paths

    Yields:
        tuple of (path, node):
            path (tuple):
                The segments of the current path
            node (dict):
                The node at the current path.
    """
    if preorder:
        yield path, doc

    for key, val in doc.iteritems():
        subpath = path + (key,)
        if isinstance(val, dict):
            for t in doc_iter(val, preorder=preorder, postorder=postorder,
                              path=subpath):
                yield t
        else:
            yield subpath, val

    if postorder:
        yield path, doc


def doc_pop(doc, path):
    """Remove and return the node that exists at the given path.

    Args:
        doc (dict):
            a hierarchical object-document.
        path (tuple):
            a list of str segments forming a path in doc.

    Returns:
        None or dict:
            If there exists a node at the given path, it is removed and
            returned. Any resulting empty nodes are removed. If there is no
            node at the path, None is returned.

    """
    feed, trail, nodes = doc_locate(doc, path)
    if feed:
        return None

    popped_node = nodes.pop()

    while nodes:
        segment = trail.pop()
        parent = nodes.pop()
        del parent[segment]
        if parent:
            break

    return popped_node


def doc_value(doc):
    if type(doc) is dict:
        return doc.get('', None)
    return doc


def doc_merge(doca, docb, merge=lambda a, b: (a, b)):
    docout = {}

    keys = set(doca.keys())
    keys.update(docb.keys())

    for key in keys:
        vala = doca.get(key)
        valb = docb.get(key)

        if isinstance(vala, dict) and isinstance(valb, dict):
            doc = doc_merge(vala, valb, merge=merge)
            if doc:
                docout[key] = doc
        else:
            val = merge(vala, valb)
            if val is not None:
                docout[key] = val

    return docout


def doc_update(target, source):
    for path, val in doc_iter(source):
        if type(val) is not dict:
            doc_set(target, path, val)


_constructors = {}


def register_constructor(constructor, name=None, sep='.'):
    if name is None:
        name = constructor.__module__
        name += sep + constructor.__name__.replace('construct_', '', 1)

    if doc_get(_constructors, name.split(sep)) is not None:
        m = ("Cannot set constructor {name!r} to {constructor!r}: "
             "constructor already exists.")
        m = m.format(name=name, constructor=constructor)
        raise ConflictError(m)

    argspec = getargspec(constructor)
    req_args = ['instance', 'spec', 'loc', 'context']
    if argspec.args != req_args:
        m = "{name!r}: a constructor arguments must be {req_args!r}"
        m = m.format(name=name, req_args=req_args)
        raise InvalidInput(m)

    _constructors[name] = constructor


def unregister_constructor(name, sep='.'):
    return doc_pop(_constructors, name.split(sep))


def autoconstructor(instance, spec, loc, context):
    if type(spec) is not dict:
        return spec

    if type(instance) is dict:
        instance[loc[-1]] = spec

    return instance


register_constructor(autoconstructor, name='autoconstruct')


def _doc_construct_normalize_spec(loc, spec):
    spec_type = type(spec)
    if spec_type is bytes:
        spec = {spec: {}}
    elif spec_type is set:
        spec = {key: {} for key in spec}
    elif spec_type is not dict:
        m = "{loc!r}: 'spec' must be a dict or byte string, not {spec!r}"
        m = m.format(loc=loc, spec=spec)
        raise InvalidInput(m)
    return spec


def _doc_construct_spec_keys(instance, doc, spec, loc, context,
                             constructors, autoconstruct,
                             allow_constructor_input,
                             sep, doc_is_basic):

    constructor_names = []
    constructed_data_keys = set()
    prefixes = []

    for key in spec.iterkeys():
        if doc_is_basic and not key.startswith(sep):
            subloc = loc + (key,)
            m = ("{loc!r}: document {doc!r} is basic "
                 "but spec requires key {key!r}")
            m = m.format(loc=subloc, doc=doc, key=key)
            raise ValidationError(m)

        if key.endswith('*'):
            prefixes.append(key[:-1])

        if key.startswith(sep):
            constructor_names.append(key)
            if not allow_constructor_input:
                continue

        subspec = spec[key]
        subdoc = doc[key] if key in doc else {}
        subloc = loc + (key,)
        instance[key] = doc_construct(
            doc=subdoc, spec=subspec, loc=subloc, context=context,
            constructors=constructors,
            autoconstruct=autoconstruct,
            allow_constructor_input=allow_constructor_input)
        constructed_data_keys.add(key)

    return instance, constructor_names, constructed_data_keys, prefixes


def _doc_construct_doc_keys(
            instance, doc, spec, loc, context,
            constructors, autoconstruct,
            allow_constructor_input,
            sep, constructed_data_keys, prefixes):

    for key in doc:
        if key in constructed_data_keys:
            continue

        index = bisect_right(prefixes, key) - 1
        subspec = {}
        if index >= 0:
            prefix = prefixes[index]
            if key.startswith(prefix):
                subspec = spec[prefix + '*']

        subloc = loc + (key,)
        subdoc = doc[key]
        instance[key] = doc_construct(
            doc=subdoc, spec=subspec, loc=subloc, context=context,
            constructors=constructors,
            autoconstruct=autoconstruct,
            allow_constructor_input=allow_constructor_input,
            sep=sep)


def _construct_doc_call_constructors(
        instance, spec, loc, context,
        constructors, autoconstruct,
        allow_constructor_input,
        sep, constructor_names):

    old_deferred_constructor_names = None
    cons_round = 0
    constructed = set()
    working_constructor_names = constructor_names

    while True:
        context['sep'] = sep
        context['constructed'] = constructed
        context['cons_round'] = cons_round

        deferred_constructor_names = []
        for constructor_name in working_constructor_names:
            subloc = loc + (constructor_name,)
            constructor = doc_get(constructors, constructor_name.split(sep))
            if constructor is None:
                if autoconstruct is True:
                    constructor = autoconstructor
                else:
                    constructor = doc_get(constructors,
                                          autoconstruct.split(sep))
                if constructor is None:
                    m = "{loc!r}: cannot find constructor {constructor_name!r}"
                    m = m.format(loc=subloc, constructor_name=constructor_name)
                    raise InvalidInput(m)

            subspec = spec[constructor_name]
            try:
                instance = constructor(instance=instance, spec=subspec,
                                       loc=subloc, context=context)
                constructed.add(constructor_name)
            except DeferConstructor as e:
                deferred_constructor_names.append(constructor_name)

        if not deferred_constructor_names:
            break

        if deferred_constructor_names == old_deferred_constructor_names:
            m = "{loc!r}: constructor deadlock {deferred!r}"
            m = m.format(loc=loc, deferred=deferred_constructor_names)
            raise InvalidInput(m)

        old_deferred_constructor_names = deferred_constructor_names
        working_constructor_names = deferred_constructor_names
        cons_round += 1

    return instance


def doc_construct(doc, spec, loc=(), context=None,
                  constructors=_constructors,
                  autoconstruct=False,
                  allow_constructor_input=False,
                  sep='.'):

    doc_is_basic = type(doc) is not dict
    spec_is_basic = type(spec) is not dict
    if spec_is_basic:
        if doc == spec:
            return doc

        if doc == {} and autoconstruct:
            return spec

        m = ("{loc!r}: spec is basic ({spec!r}), "
             "therefore doc must either be empty or equal to spec, "
             "not {doc!r}.")
        m = m.format(loc=loc, spec=spec, doc=doc)
        raise ValidationError(m)

    instance = {}
    spec = _doc_construct_normalize_spec(loc, spec)

    if context is None:
        context = {'top_spec': spec}
    elif 'top_spec' not in context:
        context['top_spec'] = spec

    instance, constructor_names, constructed_data_keys, prefixes = \
            _doc_construct_spec_keys(
                instance, doc, spec, loc, context,
                constructors, autoconstruct,
                allow_constructor_input,
                sep, doc_is_basic)

    prefixes.sort()

    if doc_is_basic:
        if instance:
            instance[''] = doc
        else:
            instance = doc
    else:
        _doc_construct_doc_keys(
            instance, doc, spec, loc, context,
            constructors, autoconstruct,
            allow_constructor_input,
            sep, constructed_data_keys, prefixes)

    instance = _construct_doc_call_constructors(
            instance, spec, loc, context,
            constructors, autoconstruct,
            allow_constructor_input,
            sep, constructor_names)

    return instance


def doc_inherit(doc, path, inherit_path):
    feed, trail, nodes = doc_locate(doc, path)
    if feed:
        return None

    inh_nodes = [nodes[0]]
    inh_paths = []
    for i in xrange(len(trail)):
        inh_paths.append(trail[:i])
        inh_nodes.append(nodes[i + 1])

    return inh_paths, inh_nodes


def doc_search(doc, name):
    findings = []
    for path, doc in doc_iter(doc):
        if path and path[-1] == name:
            findings.append(path)
    return findings


def doc_from_ns(ns, sep='/'):
    docout = {}
    for key, value in ns.iteritems():
        path = key.strip(sep).split(sep)
        doc_set(docout, path, value)
    return docout


def doc_to_ns(doc, sep='/'):
    ns = {}
    for path, val in doc_iter(doc):
        if not val or type(val) is not dict:
            ns[sep.join(path)] = val
    return ns


def random_doc(nr_nodes=32, max_depth=7):
    words = (
        'alpha',
        'beta',
        'gamma',
        'delta',
        'epsilon',
        'zeta',
        'eta',
        'theta',
        'iota',
        'kappa',
        'lambda',
        'mu',
        'nu',
        'omikron',
        'pi',
        'rho',
        'sigma',
        'tau',
        'ypsilon',
        'phi',
        'psi',
        'omega',
        'zero',
        'one',
        'two',
        'three',
        'four',
        'five',
        'six',
        'seven',
        'eight',
        'nine',
    )

    import random

    doc = {}

    for i in xrange(nr_nodes):
        depth = random.randint(1, max_depth)
        path = tuple(random.choice(words) for _ in xrange(depth))
        doc_set(doc, path, random.choice(words))

    return doc


def test():
    from pprint import pprint
    doc = random_doc()
    pprint(doc)
    a = {'hello': {'there': 9}, 'hella': {'off': 11, 'true': 12}}
    print doc_pop(a, 'hello.there'.split('.'))
    pprint(a)
    print doc_pop(a, 'hella'.split('.'))
    pprint(a)

    def constructor(instance, spec, loc, context):
        assert '.one' in instance
        assert '.three' in instance
        return instance

    spec = {'.one': 'two', '.three': 'four'}
    instance = doc_construct({}, spec,
                             allow_constructor_input=True,
                             constructors = {'one': constructor,
                                             'three': constructor,},
                             autoconstruct=True)


if __name__ == '__main__':
    test()