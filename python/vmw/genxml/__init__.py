"""genxml: typed libvirt domain XML emitter.

The public entry point is build_domain_xml(profile), which renders a
schema-valid <domain> document from a validated pydantic Profile. No
string building, no YAML dict access.

  from vmw.genxml import build_domain_xml
  xml_bytes = build_domain_xml(profile)
"""

from vmw.genxml.xml import build_domain_xml, to_string

__all__ = ["build_domain_xml", "to_string"]
