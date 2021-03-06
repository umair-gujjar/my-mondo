import os, requests, json
from datetime import datetime, date, timedelta

# for debugging only, use one at a time
save_to_cache = False
load_from_cache = False

class Mondo(object):

    def __init__(self):

        # get summary + transactions
        if load_from_cache:
            self.summary = json.load(open("cache/balance"))
            self.transactions = json.load(open("cache/transactions"))
        else:
            access_token = self._request_access_token()
            self.summary = self._request_balance(access_token)
            self.transactions = self._request_transactions(access_token)

        self.days_left_this_month = 29 - datetime.today().day
        self.recurring_merchants = []
        for x in json.load(open("recurring_merchants.json")):
            self.recurring_merchants.append(x['merchant_id'])

        self.balance = _clean_amount(self.summary['balance']*-1)
        self.spend_today = _clean_amount(self.summary['spend_today'])

    def _request_access_token(self):
        payload = {
            'grant_type': 'password',
            'client_id': os.environ['client_id'],
            'client_secret': os.environ['client_secret'],
            'username': os.environ['username'],
            'password': os.environ['password'],
            }
        r = requests.post("https://production-api.gmon.io/oauth2/token", data=payload)
        r = json.loads(r.text)
        return r["access_token"]
    def _request_balance(self, access_token):

        headers = {'Authorization': 'Bearer ' + access_token}
        payload = {
            'account_id': os.environ['account_id']
        }
        r = requests.get(
            "https://api.getmondo.co.uk/balance",
            params=payload, headers=headers)
        r = json.loads(r.text)

        if save_to_cache:
            json.dump(r, open("cache/balance",'w'))

        return r
    def _request_transactions(self, access_token):
        headers = {'Authorization': 'Bearer ' + access_token}
        payload = {
            'account_id': os.environ['account_id'],
            'expand[]': 'merchant'
        }
        r = requests.get(
            "https://production-api.gmon.io/transactions",
            params=payload, headers=headers)
        r = json.loads(r.text)["transactions"]

        if save_to_cache:
            json.dump(r, open("cache/transactions",'w'))

        return r

    def _deduct_future_transactions_from_recurring_merchants(self):
        '''
        This method:
        - returns a total_to_deduct number which is the amount we predict all
          self.recurring_merchants will charge until the end of this month
        - removes all recurring_merchants transactions to hide them from them
          the trancaction feed
        '''

        total_to_deduct = 0

        for recurring_merchant in self.recurring_merchants:
            first_transaction_date = datetime.now()
            last_transaction_date = datetime.now()

            total_spent_on_merchant = 0
            for transaction in self.transactions:

                if 'Active card check' in transaction['notes']:
                    continue
                if transaction['merchant'] is None:
                    continue
                if transaction['merchant']['id'] != recurring_merchant:
                    continue

                # add transaction to total_spent_on_merchant
                amount = float(transaction['amount'])/100*-1
                if amount > 0:
                    total_spent_on_merchant += amount

                # update first_transaction_date + last_transaction_date
                created = transaction['created'].split("T")[0]
                created = datetime.strptime(created, "%Y-%m-%d")
                if created < first_transaction_date:
                  first_transaction_date = created
                if created > last_transaction_date:
                  last_transaction_date = created

            # add to total_to_deduct
            if total_spent_on_merchant > 1:
                days_between_first_and_last_transaction = (last_transaction_date-first_transaction_date).days
                average_spent_daily = total_spent_on_merchant / days_between_first_and_last_transaction
                total_to_deduct += average_spent_daily * self.days_left_this_month

        return total_to_deduct

    @property
    def daily_budget(self):
        money_left = float(self.summary['balance'])
        daily_budget_left = money_left / self.days_left_this_month
        deduct = self._deduct_future_transactions_from_recurring_merchants()
        daily_budget_left -= deduct
        return _clean_amount(daily_budget_left)

    @property
    def batched_transactions(self):

        # hide recurring_merchants
        filtered_transactions = []
        for transaction in self.transactions:
            if transaction['merchant'] is not None:
                if transaction['merchant']['id'] not in self.recurring_merchants:
                    filtered_transactions.append(transaction)
        self.transactions = filtered_transactions

        # get list of distinct dates with purchases
        dates = []
        for x in self.transactions:
            x['amount'] = _clean_amount(x['amount'])
            x['created'] = _clean_date(x['created'])
            if x['created'] not in dates:
                dates.append(x['created'])
        dates.reverse()
        batched_transactions = []

        # group transactions into dates
        for x in dates:
            batch = []
            total_spent = 0
            for transaction in self.transactions:
                if transaction['created'] == x:
                    batch.append(transaction)
                    spent = float(transaction['amount'])
                    if spent > 0:
                        total_spent += spent
            batched_transactions.append({
            'date': x,
            'total_spent': "{0:.2f}".format(total_spent),
            'transactions': batch
            })

        return batched_transactions


def _clean_date(created):
    created = created.split("T")[0]
    created = datetime.strptime(created, "%Y-%m-%d")
    if created.date() == datetime.today().date():
        return "Today"
    elif created.date() == (date.today() - timedelta(1)):
        return "Yesterday"
    else:
        return created.strftime('%A, %d %b %Y')
def _clean_amount(amount):
    amount = float(amount)
    amount = amount/100*-1
    return "{0:.2f}".format(amount)
