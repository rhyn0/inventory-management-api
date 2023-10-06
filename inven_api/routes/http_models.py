"""Module with the base classes for API data models."""
# External Party
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


# Builds are unique in that they have an intersection against Parts and Tools
# This is a many-to-many relationship
# So we need to define a new route for this
# This is a sub-resource of Builds
class BuildRelationBase(BaseModel):
    """Model that defines the information needed to link a build to another table."""

    # validation alias since field name is not JSON like
    quantity_required: int = Field(gt=0)


class BuildRelationUpdateBase(BaseModel):
    """Define attributes of a BuildPart that can be updated.

    Do not instantiate this, it is an inheritable base.
    Even though this is a copy of BuildRelationBase, we need to define it
    seperately so that future changes to data models are easier.
    """

    # only quantity since product_id is not updatable
    quantity_required: int = Field(gt=0)


class BuildRelationFullBase(BaseModel):
    """Define a Base Build for serializing as response to HTTP request.

    This is not to be instantiated, it is an inheritable base.
    """

    model_config = ConfigDict(from_attributes=True)

    build_id: int = Field(gt=0)
