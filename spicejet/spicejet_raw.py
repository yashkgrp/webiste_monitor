import requests
import os
import string
import random
from datetime import datetime
from utils import s3
from loguru import logger
import tempfile
from utils.sentry import sentry_sdk



def spicejet_scraper(data):

    try:
        if 'Invoice/Note_Number-Master' in data.keys():
            invoice_no = data['Invoice/Note_Number-Master']
            return (spicejet_scraper_invoice(invoice_no))

        else:
            logger.info("Found Booking as source")
            pnr = data['Ticket/PNR']
            return (spicejet_scraper_pnr(pnr))

    except Exception as e:
        logger.exception(f"Got exception {e.args[0]}")
        sentry_sdk.capture_exception(e)
        return {
            "success": False,
            "message": e.args[0],
            "data": {}
        }

def spicejet_scraper_pnr(pnr, retry=5):
    if retry < 0:
        raise Exception("RETRY ATTEMPT EXCEEDED")
    try:
        url = f"https://gst.spicejet.com/gstdownload/GSTHandler.ashx?RequestType=PNRGSTDetails&PNR={pnr.upper()}&GSTMailNumber=&InvoiceNumber=&Email="
        r = requests.post(url).json()
    except Exception as e:
        logger.info("Trying to Retry")
        return (spicejet_scraper_pnr(pnr=pnr, retry=retry - 1))
    if len(r["PNRGSTDetailsList"]) > 0:
        # Record found
        logger.info(f'record {len(r["PNRGSTDetailsList"])}found')
        pnr_data = r["PNRGSTDetailsList"][0]
        logger.info(f'Found {len(r["PNRGSTDetailsList"])} record in this row')
        pdf_links = []

        for pnr_data in r["PNRGSTDetailsList"]:

            download_url = f"https://gst.spicejet.com/gstdownload/GSTHandler.ashx?RequestType=DownloadGSTInvoice&PNRNumber={pnr_data['PNRNo']}&InvoiceNumber={pnr_data['InvoiceNo']}"
            download_file = requests.get(download_url, allow_redirects=True)
            timestamp = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
            # Create a temporary file
            filename = f"{''.join(random.choices(string.ascii_uppercase + string.digits, k = 10))}_{timestamp}.pdf"
            with tempfile.NamedTemporaryFile(mode='wb') as temp_file:
                # Write to the temporary file
                airline = 'spicejet'
                temp_file.write(download_file.content)
                pdf_status, pdf_s3link = s3.upload_s3(
                    temp_file.name, filename, airline)
                if pdf_status:
                    pdf_links.append(pdf_s3link)

                else:
                    raise Exception("ERROR IN SAVING FILE PORTAL ISSUE")
        return {
            "success": True,
            "message": "FILE SAVED TO BLOB",
            "data": {'s3_link': pdf_links, 'airline': airline}
        }

    else:
        logger.info("no data found:: {}".format(r))
        raise Exception("INVALID DATA")


def spicejet_scraper_invoice(input_invoice, retry=5):
    """
    Scrape Invoice Data
    """

    if retry < 0:
        raise Exception("RETRY ATTEMPT EXCEEDED")
    try:
        url = f"https://gst.spicejet.com/gstdownload/GSTHandler.ashx?RequestType=PNRGSTDetails&PNR=&GSTMailNumber=&InvoiceNumber={input_invoice}&Email="
        r = requests.post(url).json()
    except Exception as e:
        logger.info("Trying to Retry")
        return (spicejet_scraper_invoice(input_invoice=input_invoice, retry=retry - 1))

    if len(r["PNRGSTDetailsList"]) > 0:
        logger.info(f'record {len(r["PNRGSTDetailsList"])} found')

        # Record found
        for pnr_data in r["PNRGSTDetailsList"]:

            download_url = f"https://gst.spicejet.com/gstdownload/GSTHandler.ashx?RequestType=DownloadGSTInvoice&PNRNumber={pnr_data['PNRNo']}&InvoiceNumber={pnr_data['InvoiceNo']}"
            download_file = requests.get(download_url, allow_redirects=True)
            timestamp = datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
            # Create a temporary file
            filename = f"{''.join(random.choices(string.ascii_uppercase + string.digits, k = 10))}_{timestamp}.pdf"
            pdf_links = []

            with tempfile.NamedTemporaryFile(mode='wb') as temp_file:
                # Write to the temporary file
                airline = 'spicejet'
                temp_file.write(download_file.content)
                pdf_status, pdf_s3link = s3.upload_s3(
                    temp_file.name, filename, airline)
                if pdf_status:
                    pdf_links.append(pdf_s3link)

                else:
                    raise Exception("ERROR IN SAVING FILE PORTAL ISSUE")
        return {
            "success": True,
            "message": "FILE SAVED TO BLOB",
            "data": {'s3_link': pdf_links, 'airline': airline}
        }
    else:
        logger.info("no data found:: {}".format(r))
        raise Exception("INVALID DATA")