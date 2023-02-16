from unittest import TestCase

from octodns.processor.spf import (
    SpfDnsLookupException,
    SpfDnsLookupProcessor,
    SpfValueException,
)
from octodns.record.base import Record
from octodns.zone import Zone


class TestSpfDnsLookupProcessor(TestCase):
    def test_get_spf_from_txt_values(self):
        processor = SpfDnsLookupProcessor('test')
        record = Record.new(
            Zone('unit.tests.', []),
            '',
            {'type': 'TXT', 'ttl': 86400, 'values': ['v=DMARC1\; p=reject\;']},
        )

        self.assertEqual(
            'v=spf1 include:_spf.google.com ~all',
            processor._get_spf_from_txt_values(
                [
                    'v=DMARC1\; p=reject\;',
                    'v=spf1 include:_spf.google.com ~all',
                ],
                record,
            ),
        )

        with self.assertRaises(SpfValueException):
            processor._get_spf_from_txt_values(
                [
                    'v=spf1 include:_spf.google.com ~all',
                    'v=spf1 include:_spf.google.com ~all',
                ],
                record,
            )

        self.assertEqual(
            'v=spf1 include:_spf.google.com ~all',
            processor._get_spf_from_txt_values(
                [
                    'v=DMARC1\; p=reject\;',
                    'v=spf1 include:_spf.google.com ~all',
                ],
                record,
            ),
        )

        with self.assertRaises(SpfValueException):
            processor._get_spf_from_txt_values(
                ['v=spf1 include:_spf.google.com'], record
            )

        self.assertIsNone(
            processor._get_spf_from_txt_values(
                ['v=DMARC1\; p=reject\;'], record
            )
        )

        # SPF record split across multiple character-strings, https://www.rfc-editor.org/rfc/rfc7208#section-3.3
        self.assertEqual(
            'v=spf1 include:_spf.google.com ip4:1.2.3.4 ~all',
            processor._get_spf_from_txt_values(
                [
                    'v=spf1 include:_spf.google.com',
                    ' ip4:1.2.3.4 ~all',
                    'v=DMARC1\; p=reject\;',
                ],
                record,
            ),
        )

        self.assertEqual(
            'v=spf1 +mx redirect=',
            processor._get_spf_from_txt_values(
                [
                    'v=spf1 +mx redirect=_spf.example.com',
                    'v=DMARC1\; p=reject\;',
                ],
                record,
            ),
        )

    def test_processor(self):
        processor = SpfDnsLookupProcessor('test')
        self.assertEqual('test', processor.name)

        processor = SpfDnsLookupProcessor('test')
        zone = Zone('unit.tests.', [])
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'values': [
                        'v=spf1 a include:_spf.google.com ~all',
                        'v=DMARC1\; p=reject\;',
                    ],
                },
            )
        )

        self.assertEqual(zone, processor.process_source_zone(zone))

        zone = Zone('unit.tests.', [])
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'values': [
                        'v=spf1 a ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 ip4:1.2.3.4 -all',
                        'v=DMARC1\; p=reject\;',
                    ],
                },
            )
        )

        self.assertEqual(zone, processor.process_source_zone(zone))

        zone = Zone('unit.tests.', [])
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'values': [
                        'v=spf1 a mx exists:example.com a a a a a a a a ~all',
                        'v=DMARC1\; p=reject\;',
                    ],
                },
            )
        )

        with self.assertRaises(SpfDnsLookupException):
            processor.process_source_zone(zone)

        zone = Zone('unit.tests.', [])
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'values': [
                        'v=spf1 include:example.com include:_spf.google.com include:_spf.google.com include:_spf.google.com ~all',
                        'v=DMARC1\; p=reject\;',
                    ],
                },
            )
        )

        with self.assertRaises(SpfDnsLookupException):
            processor.process_source_zone(zone)

    def test_processor_with_long_txt_values(self):
        processor = SpfDnsLookupProcessor('test')
        zone = Zone('unit.tests.', [])

        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'value': (
                        '"v=spf1 ip6:2001:0db8:85a3:0000:0000:8a2e:0370:7334 ip6:2001:0db8:85a3:0000:0000:8a2e:0370:7334"'
                        ' " ip6:2001:0db8:85a3:0000:0000:8a2e:0370:7334 ip6:2001:0db8:85a3:0000:0000:8a2e:0370:7334"'
                        ' " ip6:2001:0db8:85a3:0000:0000:8a2e:0370:7334 ~all"'
                    ),
                },
            )
        )

        self.assertEqual(zone, processor.process_source_zone(zone))

    def test_processor_skips_lenient_records(self):
        processor = SpfDnsLookupProcessor('test')
        zone = Zone('unit.tests.', [])

        lenient = Record.new(
            zone,
            'lenient',
            {
                'type': 'TXT',
                'ttl': 86400,
                'value': 'v=spf1 a a a a a a a a a a a ~all',
                'octodns': {'lenient': True},
            },
        )
        zone.add_record(lenient)

        self.assertEqual(zone, processor.process_source_zone(zone))

    def test_processor_errors_on_many_spf_values_in_record(self):
        processor = SpfDnsLookupProcessor('test')
        zone = Zone('unit.tests.', [])

        record = Record.new(
            zone,
            '',
            {
                'type': 'TXT',
                'ttl': 86400,
                'values': [
                    'v=spf1 include:mailgun.org ~all',
                    'v=spf1 include:_spf.google.com ~all',
                ],
            },
        )
        zone.add_record(record)

        with self.assertRaises(SpfValueException):
            processor.process_source_zone(zone)

    def test_processor_filters_to_records_with_spf_values(self):
        processor = SpfDnsLookupProcessor('test')
        zone = Zone('unit.tests.', [])

        zone.add_record(
            Record.new(
                zone, '', {'type': 'A', 'ttl': 86400, 'value': '1.2.3.4'}
            )
        )
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'value': 'v=spf1 a a a a a a a a a a a ~all',
                },
            )
        )

        with self.assertRaises(SpfDnsLookupException):
            processor.process_source_zone(zone)

        zone = Zone('unit.tests.', [])

        zone.add_record(
            Record.new(
                zone, '', {'type': 'A', 'ttl': 86400, 'value': '1.2.3.4'}
            )
        )
        zone.add_record(
            Record.new(
                zone,
                '',
                {
                    'type': 'TXT',
                    'ttl': 86400,
                    'values': ['AAAAAAAAAAA', 'v=spf10'],
                },
            )
        )

        self.assertEqual(zone, processor.process_source_zone(zone))
