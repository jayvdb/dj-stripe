from ...models import Customer
from ...settings import STRIPE_LIVE_MODE, subscriber_request_callback


class AutoCreateCustomerMixin:
    """Small mixin that can be included in REST API Views.

    If included, it will automatically create a Customer instance
    for the authenticated user, if does not yet exist.
    """

    pass


class AutoCustomerModelSerializerMixin:
    """Small mixin to easily provide access to the relevant customer
    inside ModelSerializers.
    """

    pass
