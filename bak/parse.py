#!/usr/bin/env python

import datetime
import decimal
import email.message
import html
import mailbox
import quopri
from pathlib import Path

import bs4
import regex as re


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
            raise TypeError("Variable must be type mailbox.mboxMessage")

        self.email_data = email

        self.labels = email["X-Gmail-Labels"]
        self.date = email["Date"]
        self.sender = email["From"]
        self.receiver = email["To"]
        self.subject = email["Subject"]
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
        content_type = "NA" if isinstance(msg, str) else msg.get_content_type()
        encoding = (
            "NA" if isinstance(msg, str) else msg.get("Content-Transfer-Encoding", "NA")
        )
        if "text/plain" in content_type and "base64" not in encoding:
            msg_text = msg.get_payload()
        elif "text/html" in content_type and "base64" not in encoding:
            msg_text = get_html_text(html=msg.get_payload(decode=True))
        elif content_type == "NA":
            msg_text = get_html_text(html=msg)
        else:
            msg_text = None
        return content_type, encoding, msg_text


class DoorDashReceipt:
    provider: str = "DoorDash"

    regex_total = re.compile(pattern=r"^Total Charged \p{Sc}(\d+\.\d+)\b")
    regex_order_id = re.compile(
        pattern=r"<(https\:\/\/www\.doordash\.com\/orders\/(\w{8}\-\w{4}\-\w{4}\-\w{4}\-\w{12}))\/>"
    )
    regex_restaurant_name = re.compile(
        pattern=r"Paid with ([\w ])+\n(\w+|\s+)+ \nTotal\: \p{Sc}(\d+\.\d+)\b",
        flags=re.MULTILINE,
    )

    # Email metadata
    email_data = None
    multipart_messages: list = None
    date_time = datetime.datetime(year=1970, month=1, day=1)
    body: email.message.Message = None
    body_as_str: str = None
    line_seperator: str = "\n"

    # Business metadata
    order_id: str = "Unknown"
    url: str = "Unknown"
    cost_total: decimal.Decimal = decimal.Decimal(value=0)
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
            content_type: str = message["Content-Type"]
            encoding: str = message["Content-Transfer-Encoding"]

            if content_type.startswith("text/plain"):
                self.email_data = message
                self.body = message

                if encoding.startswith("quoted-printable"):
                    self.body_as_str = quopri.decodestring(message.as_string()).decode(
                        encoding="utf-8"
                    )
                else:
                    self.body_as_str = str(message)

    def parse(self):
        for line in self.body_as_str.split(sep=self.line_seperator):
            self.parse_amount(line)
            self.parse_order_id(line)

    def parse_amount(self, line: str):
        search = self.regex_total.findall(string=line)
        if len(search) > 0:
            self.cost_total += decimal.Decimal(search[0])

    def parse_order_id(self, line: str):
        search = self.regex_order_id.findall(string=line)
        if len(search) > 0:
            self.url = search[0][0]
            self.order_id = search[0][1]


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
    cost_total: decimal.Decimal = decimal.Decimal(value=0)
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
            content_type: str = message["Content-Type"]
            encoding: str = message["Content-Transfer-Encoding"]

            if content_type.startswith("text/plain"):
                self.email_data = message
                self.body = message

                if encoding.startswith("quoted-printable"):
                    self.body_as_str = quopri.decodestring(message.as_string()).decode(
                        encoding="utf-8"
                    )

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
            self.cost_total += decimal.Decimal(search[0])

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

    re_ascii_chars = re.compile(pattern=r"[^\x00-\x7F]+")
    re_currency_sign = re.compile(pattern=r"\p{Sc}(\d+\.\d+)\b")
    re_restaurant_name = re.compile(
        pattern=r"^\s+You ordered from (.*+)[\r\n|\r|\n]", flags=re.MULTILINE
    )

    # Email metadata
    soup: bs4.BeautifulSoup = None
    email_data = None
    # Uber receipts do not use multipart messages
    date_time = datetime.datetime(year=1970, month=1, day=1)
    body = None
    body_as_str: str = None

    # Business metadata
    order_id: str = "Unknown"
    cost_total = decimal.Decimal(value=0)
    restaurant: str = "Unknown"

    def __init__(self, email: AbstractEmail):
        self.email_data = email.email_data
        # TODO(MinuraIddamalgoda): Parse datetime stamp
        self.body = email.body[0][2]
        self.soup = bs4.BeautifulSoup(self.body, "html5lib")
        self.body_as_str = self.body

        transfer_encoding: str = self.email_data["Content-Transfer-Encoding"]
        text_encoding = "utf_8"
        if transfer_encoding.startswith("quoted-printable"):
            if not self.body.isascii():
                ascii_stripped_body = self.re_ascii_chars.sub(
                    repl="", string=self.body
                ).encode(text_encoding)
                self.body_as_str = quopri.decodestring(ascii_stripped_body).decode(
                    text_encoding
                )

    def parse(self):
        self.parse_amount()
        self.parse_restaurant()

    def parse_amount(self):
        # Find any table data cells with a currency symbol
        amounts_found = self.soup.find_all(name="td", text=self.re_currency_sign)

        if len(amounts_found) < 1:
            print("Unable to find total amount in email")

        # Pull the numerical amounts from the <td> cell; removing any whitespace, irrelevant text, and currency symbols
        total = self.re_currency_sign.search(string=amounts_found[0].contents[0]).group(
            1
        )
        self.cost_total += decimal.Decimal(total)

    def parse_restaurant(self):
        search = self.re_restaurant_name.findall(string=self.body_as_str)
        if len(search) > 0:
            self.restaurant = html.unescape(search[0].rstrip())


def parse(mbox_file: mailbox.mbox, results: list[decimal.Decimal]):
    num_entries = len(mbox_file)
    total = decimal.Decimal(value=0)

    for index, email_obj in enumerate(mbox_file):
        email_data = AbstractEmail(email_obj)

        receipt = None
        if email_data.sender.__contains__("uber"):
            receipt = UberReceipt(email_data)
        elif email_data.sender.__contains__("doordash"):
            receipt = DoorDashReceipt(email_data)
        elif email_data.sender.__contains__("deliveroo"):
            receipt = DeliverooReceipt(email_data)
        else:
            print("Unknown delivery service found")

        if receipt is None:
            continue

        receipt.parse()

        amount = receipt.cost_total
        total += amount

        print("Parsing {} of {}".format(index, num_entries))
        print(
            "Adding {} to total {} from {} ({})\n\n".format(
                amount, total, receipt.restaurant, receipt.order_id
            )
        )

    results.append(total)


if __name__ == "__main__":
    base_dir: str = "/Users/iddamalm/code/takeout-calc/"
    default_receipt_folder: str = "receipts/"
    receipts_dir = base_dir + default_receipt_folder

    cost_total: list[decimal.Decimal] = []

    for file in Path(receipts_dir).iterdir():
        if file.is_file():
            if file.suffix.__eq__(".mbox"):
                parse(mailbox.mbox(file.absolute().resolve()), cost_total)

    print(sum(cost_total))

    # in_file = '/Users/iddamalm/code/takeout-calc/receipts/Receipts-Takeout-Uber.mbox'
    # parse(mailbox.mbox(in_file))
