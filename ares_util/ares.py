# !/usr/bin/python
# coding=utf-8

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import division
from __future__ import absolute_import
import re

from builtins import *
import requests
from requests.exceptions import RequestException

from builtins import map
from builtins import str
from builtins import range

import sys
import warnings
import logging

import xmltodict

from .settings import COMPANY_ID_LENGTH, ARES_API_URL

from .helpers import normalize_company_id_length
from .exceptions import InvalidCompanyIDError, AresNoResponseError, AresConnectionError


def call_ares(company_id):
    """
    Validate given company_id and fetch data from ARES.

    Example:
    ========
        >>> invalid_company_id = 42
        >>> call_ares(invalid_company_id)
        False

        >>> valid_company_id = "27074358"
        >>> returned_dict = call_ares(valid_company_id)
        >>> returned_dict['legal']['company_id'] == valid_company_id
        True

    @param company_id: int 8-digit number
    @return: @raise AresNoResponse:
    """
    try:
        validate_czech_company_id(company_id)
    except InvalidCompanyIDError:
        return False

    params = {'ico': company_id}

    try:
        response = requests.get(ARES_API_URL, params=params)
    except RequestException as e:
        raise AresConnectionError('Exception, ' + str(e))

    if response.status_code != 200:
        raise AresNoResponseError()

    # See: http://docs.python-requests.org/en/latest/user/quickstart/#response-content
    # If you change the encoding, Requests will use the new value of r.encoding whenever you
    # call r.text. You might want to do this in any situation where you can apply special logic
    # to work out what the encoding of the content will be. For example, HTTP and XML have
    # the ability to specify their encoding in their body.
    response.encoding = 'utf-8'
    ares_data = xmltodict.parse(response.text)

    response_root = ares_data['are:Ares_odpovedi']['are:Odpoved']
    number_of_results = response_root['D:PZA']

    if int(number_of_results) == 0:
        return False

    company_record = response_root['D:VBAS']
    address = company_record['D:AA']
    full_text_address = address.get('D:AT', '')

    result_company_info = {
        'legal': {
            'company_name': get_text_value(company_record.get('D:OF')),
            'company_id': get_text_value(company_record.get('D:ICO')),
            'company_vat_id': get_text_value(company_record.get('D:DIC')),
            'legal_form': get_legal_form(company_record.get('D:PF'))
        },
        'address': {
            'region': address.get('D:NOK'),
            'city': build_city(address.get('D:N'), full_text_address),
            'city_part': address.get('D:NCO'),
            'street': build_czech_street(address.get('D:NU', str()), address.get('D:N'),
                                         address.get('D:NCO'),
                                         address.get('D:CD') or address.get('D:CA'),
                                         address.get('D:CO'), full_text_address),
            'zip_code': get_czech_zip_code(address.get('D:PSC'), full_text_address)
        }
    }
    return result_company_info


def get_text_value(node):
    return node.get('#text', None) if node else None


def get_czech_zip_code(ares_data, full_text_address):
    if ares_data and ares_data.isdigit():
        return ares_data.strip()

    p = re.compile(r'PS[CČ]?\s+(?P<zip_code>\d+)', re.IGNORECASE | re.UNICODE)
    search = re.search(p, full_text_address)

    if search:
        return search.groupdict()["zip_code"].strip()
    else:
        logging.warning("Cannot retrieve ZIP_CODE from this: \"{0}\" address".format(full_text_address))

        # TODO Improve this code
        return ""


def build_czech_street(street_name, city_name, neighborhood, house_number, orientation_number, full_text_address):
    """
    https://cs.wikipedia.org/wiki/Ozna%C4%8Dov%C3%A1n%C3%AD_dom%C5%AF

    číslo popisné/číslo orientační
    """
    street_name = street_name or neighborhood or city_name  # Fallback in case of a small village

    if not street_name and not house_number:
        return guess_czech_street_from_full_text_address(full_text_address)

    if not orientation_number:
        return "{0}{1}".format(street_name, " %s" % house_number if house_number else "")

    return "{0} {1}/{2}".format(street_name, str(house_number), str(orientation_number))


def guess_czech_street_from_full_text_address(full_text_address):
    address_parts = full_text_address.split(',')

    # Examples:
    #   Ústí nad Labem-město, Vaníčkova 11
    #                         ^^^^^^^^^^^^
    #
    #   Bohutín 310
    #   ^^^^^^^^^^^
    if len(address_parts) < 3:
        # Get the last element of a list
        return address_parts[-1].strip()

    # Examples:
    #   Mohelnice, Družstevní 338/16, PSČ 78985
    #              ^^^^^^^^^^^^^^^^^
    elif len(address_parts) == 3:
        return address_parts[1].strip()
    else:
        logging.warning("Cannot parse this: \"%s\" address" % full_text_address)
        # TODO Improve this code
        return ""


def build_city(city, address):
    return city or address.split(',')[0].strip()


def get_legal_form(legal_form):
    """
    http://wwwinfo.mfcr.cz/ares/aresPrFor.html.cz

    @param legal_form:
    @return:
    """
    if legal_form:
        return legal_form.get('D:KPF', None)

    return None


def validate_czech_company_id(business_id):
    """
    http://www.abclinuxu.cz/blog/bloK/2008/10/kontrola-ic
    http://latrine.dgx.cz/jak-overit-platne-ic-a-rodne-cislo

    @param business_id: str
    @raise ValidationError:
    """

    if isinstance(business_id, int):
        warnings.warn("In version 0.1.5 integer parameter will be invalid. "
                      "Use string instead.", DeprecationWarning, stacklevel=2)

    business_id = str(business_id)

    # if len(business_id) != 8:
    # raise InvalidCompanyIDError("Company ID must be 8 digits long")

    try:
        digits = list(map(int, list(normalize_company_id_length(business_id))))
    except ValueError:
        raise InvalidCompanyIDError("Company ID must be a number")

    remainder = sum([digits[i] * (COMPANY_ID_LENGTH - i) for i in range(7)]) % 11
    cksum = {0: 1, 10: 1, 1: 0}.get(remainder, 11 - remainder)
    if digits[7] != cksum:
        raise InvalidCompanyIDError("Wrong Company ID checksum")

    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Pass company ID as a function argument')
        sys.exit(2)

    company_id_to_check = sys.argv[1]
    ares_response = call_ares(company_id_to_check)

    if not ares_response:
        print("Company ID \"{0}\" is not valid".format(company_id_to_check))
    else:
        print(ares_response)

    sys.exit(0)
