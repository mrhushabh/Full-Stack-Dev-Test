"""Shared model base.

One convention on each side of the wire: snake_case in Python, camelCase in JSON.

The alias generator sets both directions deliberately. Serializing to camelCase
while only *accepting* snake_case produces an asymmetric contract -- the client
POSTs back the exact shape the server just handed it and gets a 422. That is
precisely what happens between `GET /presets/{id}/request` and `POST /estimates`,
where the response of one is the request body of the other.

`populate_by_name` keeps snake_case working on input too, so hand-written curl and
the Python tests stay readable.

Fields that declare an explicit `validation_alias` -- the messy-data reconciliation
in `domain.py` -- override the generator, which is why those spell out every
accepted variant themselves.
"""

from __future__ import annotations

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )
