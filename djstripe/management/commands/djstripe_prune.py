"""
prune command.
"""
from .djstripe_sync_models import Command as MultiModelCommand

from ... import models, settings

import stripe


class Command(MultiModelCommand):
    """Prune (deactivate or delete) from dj-stripe and/or stripe."""

    help = "Delete or Mark records inactive."

    def add_arguments(self, parser):
        super(Command, self).add_arguments(parser)

        parser.add_argument(
            "--delete", action='store_true',
            help="delete data",
        )

        parser.add_argument(
            "--existing", action='store_true',
            help="process data in djstripe only",
        )

        parser.add_argument(
            "--only-missing", action='store_true',
            help="process data not in stripe dashboard",
        )

    def _should_sync_model(self, model):
        rv, msg = super(Command, self)._should_sync_model(model)
        if not rv:
            return rv, msg

        if self._options['delete']:
            # TODO: The following fail with KeyError: 'delete'
            # Likely many more do, and inspection of the model is better
            if model is models.BalanceTransaction:
                return False, "BalanceTransaction can not be deleted"
            if model is models.PaymentMethod:
                return False, "PaymentMethod can not be deleted"
            if model is models.PaymentIntent:
                return False, "PaymentIntent can not be deleted"
            if model is models.Charge:
                return False, "PaymentMethod can not be deleted"
            return True, ""

        if 'active' in [f.name for f in model._meta.fields]:
            return False, "{} has no 'active' field".format(model.__name__)

        return True, ""

    def sync_model(self, model, account_id=None, record_id=None):
        """Call set inactive for each record."""
        model_name = model.__name__
        existing = self._options['existing']
        delete = self._options['delete']
        only_delete_if_missing = self._options['only_missing']

        should_sync, reason = self._should_sync_model(model)
        if not should_sync:
            self.stdout.write(f"Skipping {model}: {reason}")
            return

        action = "Deleting" if delete else "Deactivating" 

        if account_id:
            self.stdout.write("{} {} for {}:".format(action, model_name, account_id))
        else:
            self.stdout.write("{} {}:".format(action, model_name))

        assert not settings.STRIPE_LIVE_MODE
        count = 0
        failed = 0

        # TODO: Use this mapping to determine deactivation status
        status_mapping = {
            'Subscription': 'incomplete',
        }

        if existing:
            for obj in model.objects.all():
                if delete:
                    self.delete(obj, only_delete_if_missing=only_delete_if_missing)
                    continue

                status_choices = None
                if 'active' not in [f.name for f in model._meta.fields]:
                    if 'status' in [f.name for f in model._meta.fields]:
                        field_def = [f for f in model._meta.fields if f.name == 'status'][0]
                        status_choices = field_def.choices
                        # TODO: check 'active' in field.choices, and use
                        # status_mapping above
                        current_value = getattr(obj, 'status')
                        if current_value != 'active':
                            print('{}.status is {}'.format(obj, current_value))
                        setattr(obj, 'status', 'incomplete')
                    else:
                        print('No active or status on {}'.format(model))
                else:
                    obj.active = False
                    pass

                obj.save()

                try:
                    instance = obj.api_retrieve(
                        stripe_account=obj.djstripe_owner_account.id
                    )
                except stripe.error.InvalidRequestError:
                    print("Unable to fetch stripe object {0}".format(obj.id))
                    pass
                else:
                    if status_choices:
                        # TODO: The following fails on Subscription
                        # Request req_ViACmoehLTRTTv: Received unknown parameter: status
                        instance.status = 'incomplete'
                    else:
                        instance.active = False
                    instance.save()
                print("Deactivated object {0}".format(obj.id))

            return

        for list_kwargs in self.get_list_kwargs(model, account_id, record_id):
            for stripe_obj in list(model.api_list(**list_kwargs)):
                try:
                    try:
                        djstripe_obj = model.objects.get(id=stripe_obj.id)
                    except model.DoesNotExist:
                        self.stderr.write(
                            "  id={id} not in djstripe".format(
                               id=stripe_obj.id,
                            )
                        )
                        if delete:
                            stripe_obj.delete()
                        continue

                    # TODO: implement archive (non-delete)

                    if delete:
                        self.delete(djstripe_obj)

                    count += 1
                    self.stdout.write(
                        "  id={id}, pk={pk} ({djstripe_obj})".format(
                            id=djstripe_obj.id,
                            pk=djstripe_obj.pk,
                            djstripe_obj=djstripe_obj,
                        )
                    )
                except Exception as e:
                    failed += 1
                    self.stderr.write(
                        "  id={id} failed: {e}".format(
                            id=stripe_obj.id,
                            e=str(e),
                        )
                    )
                    raise

    def delete(self, obj, only_delete_if_missing=False):
        try:
            instance = obj.api_retrieve(
                stripe_account=obj.djstripe_owner_account.id
            )
        except stripe.error.InvalidRequestError:
            print("Unable to fetch stripe object {}".format(obj.id))
            if only_delete_if_missing:
                print('deleting {}'.format(obj))
                obj.delete()
                return
        else:
            if only_delete_if_missing:
                return

            try:
                instance.delete()
            except stripe.error.InvalidRequestError as e:
                print("Unable to delete stripe object {}: {}".format(obj.id, e))
                return

        print('deleting {}'.format(obj))
        obj.delete()
