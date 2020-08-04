from typing import List

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from ... import models, settings


class Command(BaseCommand):
    """Sync models from stripe."""

    help = "Sync models from stripe."

    def add_arguments(self, parser):
        parser.add_argument(
            "args",
            metavar="ModelName",
            nargs="*",
            help="restricts sync to these model names (default is to sync all "
            "supported models)",
        )
        parser.add_argument(
            "--account",
            help="restricts sync to one account",
        )
        parser.add_argument(
            "--filter",
            help="restricts sync to records matching this filter",
        )

    def handle(self, *args, **options):
        app_label = "djstripe"
        app_config = apps.get_app_config(app_label)
        model_list = []  # type: List[models.StripeModel]

        if options['account']:
            accounts = [options['account']]
        else:
            accounts = self._get_all_account_ids()

        print(accounts)

        if args:
            for model_label in args:
                try:
                    model = app_config.get_model(model_label)
                except LookupError:
                    raise CommandError(
                        "Unknown model: {}.{}".format(app_label, model_label)
                    )

                model_list.append(model)
        else:
            model_list = list(app_config.get_models())

        if options['filter']:
            record_filter = options['filter']
            if '=' in record_filter:
                key, _, value = record_filter.partition('=')
                key, value = key.strip(), value.strip()
                record_filter = {key: value}
            else:
                record_filter = {'ids': [record_filter]}
        else:
            record_filter = None

        counts = {}
        for account in accounts:
            counts[account] = 0
            for model in model_list:
                if model is models.ApplicationFee: continue
                if model is models.Payout: continue

                count = self.sync_model(model, account, record_filter)
                if count:
                    counts[account] += count

        print(counts)

    def _should_sync_model(self, model):
        if not issubclass(model, models.StripeModel):
            return False, "not a StripeModel"

        if model.stripe_class is None:
            return False, "no stripe_class"

        if not hasattr(model.stripe_class, "list"):
            return False, "no stripe_class.list"

        if model is models.UpcomingInvoice:
            return False, "Upcoming Invoices are virtual only"

        if model is models.SubscriptionItem:
            return False, "Sync subscription item must be sync from the Subscription"

        if not settings.STRIPE_LIVE_MODE:
            if model is models.ScheduledQueryRun:
                return False, "only available in live mode"

        return True, ""

    def _get_all_account_ids(self):
        accounts = [account.id for account in models.Account.api_list()]
        stripe_obj = models.Account.stripe_class.retrieve(
            api_key=settings.STRIPE_SECRET_KEY
        )
        accounts = [stripe_obj.id] + accounts
        return accounts

    def sync_model(self, model, account_id=None, record_id=None):
        model_name = model.__name__

        should_sync, reason = self._should_sync_model(model)
        if not should_sync:
            self.stdout.write(f"Skipping {model}: {reason}")
            return

        if account_id:
            self.stdout.write("Syncing {} for {}:".format(model_name, account_id))
        else:
            self.stdout.write("Syncing {}:".format(model_name))

        count = 0
        failed = 0
        for list_kwargs in self.get_list_kwargs(model, account_id, record_id):
            if True:
                if model is models.Account:
                    # special case, since own account isn't returned by Account.api_list
                    stripe_obj = models.Account.stripe_class.retrieve(
                        api_key=settings.STRIPE_SECRET_KEY
                    )
                    count += 1
                    djstripe_obj = model.sync_from_stripe_data(stripe_obj)
                    self.stdout.write(
                        "  id={id}, pk={pk} ({djstripe_obj})".format(
                            id=djstripe_obj.id,
                            pk=djstripe_obj.pk,
                            djstripe_obj=djstripe_obj,
                        )
                    )

                for stripe_obj in model.api_list(**list_kwargs):
                    try:
                        djstripe_obj = model.sync_from_stripe_data(stripe_obj)
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

        if count == 0:
            self.stdout.write("  (no results, {} failed)".format(failed))
        elif failed:
            self.stdout.write(
                "  Synced {count} {model_name}; {failed} failed".format(
                    count=count, model_name=model_name, failed=failed,
                )
            )
        else:
            self.stdout.write(
                "  Synced {count} {model_name}".format(
                    count=count, model_name=model_name
                )
            )
        return count

    def get_list_kwargs(self, model, account_id=None, record_limit=None):
        """
        Returns a sequence of kwargs dicts to pass to model.api_list

        This allows us to sync models that require parameters to api_list

        :param model:
        :return: Sequence[dict]
        """
        if not record_limit:
            record_limit = {}
        if model is models.PaymentMethod:
            # special case
            all_list_kwargs = (
                {"customer": stripe_customer.id, "type": "card",
                 "stripe_account": account_id}
                for stripe_customer in models.Customer.api_list(
                    stripe_account=account_id)
            )
        elif account_id:
            all_list_kwargs = [{'stripe_account': account_id, **record_limit}]
        else:
            # one empty dict so we iterate once
            all_list_kwargs = [{}]

        return all_list_kwargs
