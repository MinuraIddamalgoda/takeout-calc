#!/usr/bin/env python

import decimal
import email.message
import mailbox
import datetime
from re import Match
from typing import AnyStr

import bs4
import regex as re
import quopri


def get_html_text(html, parser: str = "html5lib"):
    try:
        return bs4.BeautifulSoup(html, parser).prettify()
    except AttributeError:  # message contents empty
        return None


class AbstractEmail:
    email_data = None
    multipart_messages: list = None
    labels = None
    date = None
    sender: str = None
    receiver: str = None
    subject: str = None
    body = None

    def __init__(self, email: mailbox.mboxMessage):
        if not isinstance(email, mailbox.mboxMessage):
            raise TypeError('Variable must be type mailbox.mboxMessage')

        self.email_data = email

        self.labels = email['X-Gmail-Labels']
        self.date = email['Date']
        self.sender = email['From']
        self.receiver = email['To']
        self.subject = email['Subject']
        self.body = self.read_email_payload()

    def read_email_payload(self):
        email_payload = self.email_data.get_payload()
        if self.email_data.is_multipart():
            self.multipart_messages = list(self._get_email_messages(email_payload))
        else:
            self.multipart_messages = [email_payload]
        return [self._read_email_text(msg) for msg in self.multipart_messages]

    def _get_email_messages(self, email_payload):
        for message in email_payload:
            if isinstance(message, (list, tuple)):
                for sub_message in self._get_email_messages(message):
                    yield sub_message
            elif message.is_multipart():
                for sub_message in self._get_email_messages(message.get_payload()):
                    yield sub_message
            else:
                yield message

    @staticmethod
    def _read_email_text(msg):
        content_type = 'NA' if isinstance(msg, str) else msg.get_content_type()
        encoding = 'NA' if isinstance(msg, str) else msg.get('Content-Transfer-Encoding', 'NA')
        if 'text/plain' in content_type and 'base64' not in encoding:
            msg_text = msg.get_payload()
        elif 'text/html' in content_type and 'base64' not in encoding:
            msg_text = get_html_text(html=msg.get_payload(decode=True))
        elif content_type == 'NA':
            msg_text = get_html_text(html=msg)
        else:
            msg_text = None
        return content_type, encoding, msg_text


class DeliverooReceipt:
    provider: str = "Deliveroo"

    regex_total = re.compile(pattern=r"^\s{2}Total\s+\p{Sc}(\d+\.\d+)$")
    regex_order_id = re.compile(pattern=r"Your Receipt for Order \#(\d+)\b")
    regex_restaurant_name = re.compile(pattern=r"^(.*)( has your order!)$")

    # Email metadata
    email_data = None
    multipart_messages: list = None
    date_time = datetime.datetime(year=1970, month=1, day=1)
    body: email.message.Message = None
    body_as_str: str = None
    line_seperator: str = "\n"

    # Business metadata
    order_id: str = "Unknown"
    amount: decimal.Decimal = decimal.Decimal(value=0)
    restaurant: str = "Unknown"

    def __init__(self, email: AbstractEmail):
        """
        We can either read a plaintext body or parse the full HTML body. Here,
        we'll read the plaintext as it is easier.

        :param email: The Deliveroo email receipt
        """
        # TODO(MinuraIddamalgoda): Parse datetime stamp
        self.multipart_messages = email.multipart_messages

        for message in self.multipart_messages:
            content_type: str = message['Content-Type']
            encoding: str = message['Content-Transfer-Encoding']

            if content_type.startswith('text/plain'):
                self.email_data = message
                self.body = message

                if encoding.startswith("quoted-printable"):
                    self.body_as_str = quopri.decodestring(message.as_string()).decode(encoding='utf-8')

                    if not self.body_as_str.isascii():
                        self.line_seperator = "\r\n"

                else:
                    self.body_as_str = str(message)

    def parse(self):
        for line in self.body_as_str.split(sep=self.line_seperator):
            self.parse_amount(line)
            self.parse_restaurant(line)
            self.parse_order_id(line)

    def parse_amount(self, line: str):
        search = self.regex_total.findall(string=line)
        if len(search) > 0:
            self.amount += decimal.Decimal(search[0])

    def parse_restaurant(self, line: str):
        search = self.regex_restaurant_name.findall(string=line)
        if len(search) > 0:
            self.restaurant = search[0][0]

    def parse_order_id(self, line: str):
        search = self.regex_order_id.findall(string=line)
        if len(search) > 0:
            self.order_id = search[0]


class UberReceipt:
    provider: str = "Uber Eats"

    regex_total = re.compile(r'\p{Sc}(\d+\.\d+)\b')

    # Email metadata
    email_data = None
    # Uber receipts do not use multipart messages
    date_time = datetime.datetime(year=1970, month=1, day=1)
    body = None

    # Business metadata
    order_id: str = "Unknown"
    amount = decimal.Decimal(value=0)
    restaurant: str = "Unknown"

    def __init__(self, email: AbstractEmail):
        self.email_data = email.email_data
        # TODO(MinuraIddamalgoda): Parse datetime stamp
        self.body = email.body[0][2]

    def parse(self):
        self.parse_amount()
        self.parse_restaurant()

    def parse_amount(self):
        amounts_found = self.regex_total.findall(string=self.body)

        if len(amounts_found) < 1:
            print("Unable to find total amount in email")

        self.amount += decimal.Decimal(amounts_found[0])

    def parse_restaurant(self):
        self.restaurant = "Unknown"
        print("TODO(MinuraIddamalgoda): Parse restaurant")


mbox_obj = mailbox.mbox('/Users/iddamalm/code/takeout-calc/receipts/Receipts-Takeout-Uber.mbox')

num_entries = len(mbox_obj)
total = decimal.Decimal(value=0)

for idx, email_obj in enumerate(mbox_obj):
    email_data = AbstractEmail(email_obj)

    receipt = None
    if email_data.sender.__contains__("uber"):
        receipt = UberReceipt(email_data)
    elif email_data.sender.__contains__("doordash"):
        print("DoorDash has not been implemented yet")
        pass
    elif email_data.sender.__contains__("deliveroo"):
        receipt = DeliverooReceipt(email_data)
    else:
        print("Unknown delivery service found")

    if receipt is None:
        continue

    receipt.parse()

    amount = receipt.amount
    total += amount

    print("Parsing {} of {}".format(idx, num_entries))
    print("Adding {} to total {} from {} ({})\n\n".format(amount, total, receipt.restaurant, receipt.order_id))

print("Sum:\t{}".format(total))
