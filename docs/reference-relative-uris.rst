.. _reference.discarded_uris:

``discarded_uris``
==================

The number of relative :abbr:`URI (Uniform Resource Identifier)`\s that were
discarded while completing them because the completed
:abbr:`URI (Uniform Resource Identifier)` did not use the ``http`` or
``https`` scheme.

See :ref:`advanced.base.discarded` for more details.


.. _reference.relative_uris:

``relative_uris``
=================

A dictionary that maps each completed :abbr:`URI (Uniform Resource Identifier)`
to the original relative reference as it was written in the feed.

The parsed data contains the completed, absolute :abbr:`URI (Uniform Resource
Identifier)`\s; this mapping lets clients see the relative text they came from.
See :ref:`advanced.base.original` for more details.
