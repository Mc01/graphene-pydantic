import typing as T
import uuid
import enum
import datetime
import decimal

import pytest
import graphene
import graphene.types
import pydantic
from pydantic import create_model, BaseModel

from graphene_pydantic_fix.converters import convert_pydantic_field, ConversionError
from graphene_pydantic_fix.registry import get_global_registry
from graphene_pydantic_fix import converters


def _get_field_from_spec(name, type_spec_or_default):
    kwargs = {name: type_spec_or_default}
    m = create_model("model", **kwargs)
    return m.__fields__[name]


def _convert_field_from_spec(name, type_spec_or_default):
    return convert_pydantic_field(
        _get_field_from_spec(name, type_spec_or_default), get_global_registry()
    )


def test_required_string():
    field = _convert_field_from_spec("s", (str, ...))
    assert field is not None
    assert isinstance(field, graphene.Field)
    # The ellipsis in the type spec means required
    assert isinstance(field.type, graphene.NonNull)
    assert field.type.of_type == graphene.String


def test_default_values():
    field = _convert_field_from_spec("s", "hi")
    assert field is not None
    assert isinstance(field, graphene.Field)
    # there's a default value, so it's not required
    assert not isinstance(field.type, graphene.NonNull)
    assert field.type == graphene.String
    assert field.default_value == "hi"


@pytest.mark.parametrize(
    "input, expected",
    [
        ((bool, False), graphene.Boolean),
        ((float, 0.1), graphene.Float),
        ((int, 6), graphene.Int),
        ((str, "hi"), graphene.String),
        ((uuid.UUID, uuid.uuid4()), graphene.UUID),
        ((datetime.date, datetime.date(2019, 1, 1)), graphene.Date),
        ((datetime.time, datetime.time(15, 29)), graphene.Time),
        ((datetime.datetime, datetime.datetime(2019, 1, 1, 1, 37)), graphene.DateTime),
    ],
)
def test_builtin_scalars(input, expected):
    field = _convert_field_from_spec("attr", input)
    assert isinstance(field, graphene.Field)
    assert field.type == expected
    assert field.default_value == input[1]


def test_union():
    field = _convert_field_from_spec("attr", (T.Union[int, float, str], 5.0))
    assert issubclass(field.type, graphene.Union)
    assert field.default_value == 5.0
    assert field.type.__name__.startswith("UnionOf")


def test_mapping():
    with pytest.raises(ConversionError) as exc:
        _convert_field_from_spec("attr", (T.Dict[str, int], {"foo": 5}))
    assert exc.value.args[0] == "Don't know how to handle mappings in Graphene."


def test_decimal(monkeypatch):
    monkeypatch.setattr(converters, "DECIMAL_SUPPORTED", True)
    field = _convert_field_from_spec("attr", (decimal.Decimal, decimal.Decimal(1.25)))
    assert field.type.__name__ == "Decimal"

    monkeypatch.setattr(converters, "DECIMAL_SUPPORTED", False)
    field = _convert_field_from_spec("attr", (decimal.Decimal, decimal.Decimal(1.25)))
    assert field.type.__name__ == "Float"


def test_iterables():
    field = _convert_field_from_spec("attr", (T.List[int], [1, 2]))
    assert isinstance(field.type, graphene.types.List)

    field = _convert_field_from_spec("attr", (list, [1, 2]))
    assert field.type == graphene.types.List

    field = _convert_field_from_spec("attr", (T.Set[int], {1, 2}))
    assert isinstance(field.type, graphene.types.List)

    field = _convert_field_from_spec("attr", (set, {1, 2}))
    assert field.type == graphene.types.List

    field = _convert_field_from_spec("attr", (T.Tuple[int, float], (1, 2.2)))
    assert isinstance(field.type, graphene.types.List)

    field = _convert_field_from_spec("attr", (T.Tuple[int, ...], (1, 2.2)))
    assert isinstance(field.type, graphene.types.List)

    field = _convert_field_from_spec("attr", (tuple, (1, 2)))
    assert field.type == graphene.types.List

    field = _convert_field_from_spec("attr", (T.Union[None, int], 1))
    assert field.type == graphene.types.Int


def test_enum():
    class Color(enum.Enum):
        RED = 1
        GREEN = 2

    field = _convert_field_from_spec("attr", (Color, Color.RED))
    assert field.type.__name__ == "Color"
    assert field.type._meta.enum == Color


def test_existing_model():
    from graphene_pydantic_fix import PydanticObjectType

    class Foo(BaseModel):
        name: str

    class GraphFoo(PydanticObjectType):
        class Meta:
            model = Foo

    field = _convert_field_from_spec("attr", (Foo, Foo(name="bar")))
    assert field.type == GraphFoo


def test_unknown():
    with pytest.raises(ConversionError) as exc:
        _convert_field_from_spec("attr", (create_model("Model", size=int), None))
    assert "Don't know how to convert" in exc.value.args[0]
    if pydantic.version.VERSION < "1.0":
        assert "Field(attr type=Model default=None)" in exc.value.args[0]
    else:
        # this worked at least as of 1.1
        assert (
            "ModelField(name='attr', type=Optional[Model], required=False, default=None)"
            in exc.value.args[0]
        )
