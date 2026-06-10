"""SVG / MathML attribute case restoration.

lxml's HTML parser (libxml2 HTML4 mode) unconditionally lowercases every
attribute. epubcheck and the SVG specification require camelCase
attribute names like ``viewBox`` and ``preserveAspectRatio``; lowercased
forms are rejected.

This module walks a parsed tree and renames known case-sensitive SVG /
MathML attributes back to their spec-mandated form. The rename is scoped
to SVG / MathML subtrees, so plain HTML attributes (which are correctly
lowercase) are left alone.

The mapping is a closed enumeration of SVG 1.1 + MathML 3 attributes
known to require case preservation. New attributes can be appended
without other code changes.
"""

from __future__ import annotations

from lxml import etree

_SVG_CASE_SENSITIVE_ATTRS: dict[str, str] = {
    "attributename": "attributeName",
    "attributetype": "attributeType",
    "baseprofile": "baseProfile",
    "calcmode": "calcMode",
    "clippathunits": "clipPathUnits",
    "contentscripttype": "contentScriptType",
    "contentstyletype": "contentStyleType",
    "diffuseconstant": "diffuseConstant",
    "edgemode": "edgeMode",
    "externalresourcesrequired": "externalResourcesRequired",
    "filterunits": "filterUnits",
    "glyphref": "glyphRef",
    "gradienttransform": "gradientTransform",
    "gradientunits": "gradientUnits",
    "kernelmatrix": "kernelMatrix",
    "kernelunitlength": "kernelUnitLength",
    "keypoints": "keyPoints",
    "keysplines": "keySplines",
    "keytimes": "keyTimes",
    "lengthadjust": "lengthAdjust",
    "limitingconeangle": "limitingConeAngle",
    "markerheight": "markerHeight",
    "markerunits": "markerUnits",
    "markerwidth": "markerWidth",
    "maskcontentunits": "maskContentUnits",
    "maskunits": "maskUnits",
    "numoctaves": "numOctaves",
    "pathlength": "pathLength",
    "patterncontentunits": "patternContentUnits",
    "patterntransform": "patternTransform",
    "patternunits": "patternUnits",
    "pointsatx": "pointsAtX",
    "pointsaty": "pointsAtY",
    "pointsatz": "pointsAtZ",
    "preservealpha": "preserveAlpha",
    "preserveaspectratio": "preserveAspectRatio",
    "primitiveunits": "primitiveUnits",
    "refx": "refX",
    "refy": "refY",
    "repeatcount": "repeatCount",
    "repeatdur": "repeatDur",
    "requiredextensions": "requiredExtensions",
    "requiredfeatures": "requiredFeatures",
    "specularconstant": "specularConstant",
    "specularexponent": "specularExponent",
    "spreadmethod": "spreadMethod",
    "startoffset": "startOffset",
    "stddeviation": "stdDeviation",
    "stitchtiles": "stitchTiles",
    "surfacescale": "surfaceScale",
    "systemlanguage": "systemLanguage",
    "tablevalues": "tableValues",
    "targetx": "targetX",
    "targety": "targetY",
    "textlength": "textLength",
    "viewbox": "viewBox",
    "viewtarget": "viewTarget",
    "xchannelselector": "xChannelSelector",
    "ychannelselector": "yChannelSelector",
    "zoomandpan": "zoomAndPan",
}

_SVG_LOCAL_NAMES = {"svg", "math"}


def restore_svg_attribute_case(tree: etree._Element) -> None:
    """Walk ``tree`` and rename SVG / MathML attributes to their
    camelCase spec form. In-place mutation. No-op on trees with no SVG /
    MathML elements.
    """
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        local = el.tag.rsplit("}", 1)[-1].lower()
        is_svg_subtree = local in _SVG_LOCAL_NAMES or any(
            isinstance(a.tag, str) and a.tag.rsplit("}", 1)[-1].lower() in _SVG_LOCAL_NAMES
            for a in el.iterancestors()
        )
        if not is_svg_subtree:
            continue
        for low, proper in _SVG_CASE_SENSITIVE_ATTRS.items():
            if low in el.attrib:
                el.set(proper, el.attrib.pop(low))
