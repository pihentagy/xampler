import datetime
import functools
import logging
import random
import string
from typing import *

import lxml.etree as ET
import rstr
import xmlschema

MAX_REPEAT = 100
INDENT_SHIFT = 4


@functools.lru_cache
def indent(num: int):
    return ' ' * INDENT_SHIFT * num


@functools.lru_cache
def num_parents(node):
    if node is None:
        return 0
    return sum(1 for _ in node.iterancestors())


def indent_for(node):
    return indent(num_parents(node))


ts_min = int(datetime.datetime(1970, 1, 1).timestamp())
ts_max = int(datetime.datetime(2050, 1, 1).timestamp())

primitive_values = {
    '{http://www.w3.org/2001/XMLSchema}dateTime':
        lambda: datetime.datetime.fromtimestamp(random.randint(ts_min, ts_max)).strftime('%Y-%m-%dT%H:%M:%SZ'),
    '{http://www.w3.org/2001/XMLSchema}string':
        lambda: rstr.rstr(string.ascii_letters + string.digits + string.punctuation, 2000),
    '{http://www.w3.org/2001/XMLSchema}int':
        lambda: random.randint(-2 ** 32, 2 ** 31),
    '{http://www.w3.org/2001/XMLSchema}long':
        lambda: random.randrange(-2 ** 64, 2 ** 63),
    '{http://www.w3.org/2001/XMLSchema}decimal':
        lambda: random.uniform(-1e32, 1e32)
}


def xample(
        root_xsd_node: xmlschema.XsdElement,
        dest_root: ET.Element,
        repetitions_callback: Callable[[xmlschema.XsdElement], int],
        value_generatorrs: Callable[[xmlschema.XsdElement, ET.Element], Optional[object]],
        element_callback: Callable[[xmlschema.XsdElement], None]):
    def gen_nodes(xsd_node: xmlschema.XsdElement, dest_elem: ET.Element):
        """
        Handles repetition of the node
        :param xsd_node:
        :param dest_elem:
        """
        min_occ, max_occ = xsd_node.min_occurs, xsd_node.max_occurs

        repeat = repetitions_callback(xsd_node)
        if repeat is None:
            if max_occ is None:
                repeat = random.randint(min_occ, MAX_REPEAT)
            else:
                repeat = random.randint(min_occ, max_occ)

        logging.info(f'{indent_for(dest_elem)}<!-- {xsd_node.local_name} {repeat} ({min_occ}-{max_occ}) -->')
        if xsd_node.annotation:
            logging.info(
                f'{indent_for(dest_elem)}<!--{" ".join(d.text for d in xsd_node.annotation.documentation)} -->')

        for i in range(repeat):
            logging.info(f'{indent_for(dest_elem)}<{xsd_node.local_name}>[{i}]')
            new_element = ET.SubElement(dest_elem, xsd_node.name)
            gen_node(xsd_node, new_element)
            logging.info(f'{indent_for(dest_elem)}</{xsd_node.local_name}>')

    def gen_node(xsd_elem: xmlschema.XsdElement, dest_elem):
        def gen_attrs():
            for attr_name in xsd_elem.attributes:
                attr = xsd_elem.attributes[attr_name]
                # TODO use repetitions callback to determine attribute repetition
                if attr.is_prohibited():
                    continue
                if attr.is_optional():
                    repeat = repetitions_callback(attr)
                    if repeat is None:
                        repeat = random.randrange(2) == 0
                    if repeat is False:
                        continue
                attr_value = value_generator(attr, dest_elem)
                dest_elem.set(attr_name, str(attr_value))

        """
        Generates one node, handling complex/simple node type
        """
        if xsd_elem.type.has_complex_content():
            element_callback(xsd_elem)
            assert xsd_elem.type.content.model == 'sequence'
            for n in xsd_elem.type.content:
                gen_nodes(n, dest_elem)
        else:
            gen_attrs()
            value = value_generator(xsd_elem, dest_elem)
            dest_elem.text = str(value)

    def value_generator(xsd_elem: xmlschema.XsdElement, node: ET.Element) -> str:
        value = value_generatorrs(xsd_elem, node)
        if value is None:
            value = by_type_value_generator(xsd_elem)
        return value

    def by_type_value_generator(xsd_elem):
        """
        Generates one value (result is string or numeric)
        Works for:
        * atomic types
        * restrictions
        * complex types with attr_name simple value
        """
        if not xsd_elem.type.is_simple():
            assert xsd_elem.type.has_simple_content()
            return generate_by_type(xsd_elem.type.content)
        elif xsd_elem.type.is_restriction():
            return generate_by_restriction(xsd_elem)
        elif xsd_elem.type.is_atomic():
            return generate_by_type(xsd_elem.type)
        else:
            raise TypeError('Unknown type', xsd_elem.type)

    def generate_by_restriction(xsd_elem):
        if len(xsd_elem.type.validators) == 0:  # no validator, just return default
            return generate_by_type(xsd_elem.type.base_type)
        elif len(xsd_elem.type.facets) == 1 and \
                isinstance(xsd_elem.type.validators[0], xmlschema.validators.facets.XsdEnumerationFacets):
            return random.choice(xsd_elem.type.validators[0].enumeration)
        min_len, max_len = None, None
        pattern = None
        for v in xsd_elem.type.facets.values():
            if isinstance(v, xmlschema.validators.facets.XsdMinLengthFacet):
                min_len = v.value
            elif isinstance(v, xmlschema.validators.facets.XsdMaxLengthFacet):
                max_len = v.value
            elif isinstance(v, xmlschema.validators.facets.XsdPatternFacets):
                assert len(v.patterns) == 1
                pattern = v.patterns[0].pattern
            else:
                logging.critical(f"Unknown facet {v}")
        if pattern is not None:
            if min_len or max_len:
                logging.warning(f"Cannot take into consideration min and max length when using regex pattern")
            return rstr.xeger(pattern)
        else:
            if min_len is None:
                min_len = 0  # TODO Should it be 0 or 1?
            return rstr.rstr(string.ascii_letters + string.digits + string.punctuation, min_len, max_len)

    def generate_by_type(atomic_type):
        return primitive_values[atomic_type.name]()

    gen_nodes(root_xsd_node, dest_root)


'''
TODO
- missing types
- missing restrictions
- option for mandatory only (only generate mandatory tags)
- validate generated values
- validate generated restrictions
- can attributes have newlines?
'''
