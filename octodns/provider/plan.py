#
#
#

from io import StringIO
from logging import DEBUG, ERROR, INFO, WARN, getLogger
from sys import stdout


class UnsafePlan(Exception):
    pass


class RootNsChange(UnsafePlan):
    def __init__(self):
        super().__init__('Root NS record change, force required')


class TooMuchChange(UnsafePlan):
    def __init__(
        self,
        why,
        update_pcent,
        update_threshold,
        change_count,
        existing_count,
        name,
    ):
        msg = (
            f'[{name}] {why}, {update_pcent:.2f}% is over {update_threshold:.2f}% '
            f'({change_count}/{existing_count}), force required'
        )
        super().__init__(msg)


class Plan(object):
    log = getLogger('Plan')

    MAX_SAFE_UPDATE_PCENT = 0.3
    MAX_SAFE_DELETE_PCENT = 0.3
    MIN_EXISTING_RECORDS = 10

    def __init__(
        self,
        existing,
        desired,
        changes,
        exists,
        update_pcent_threshold=MAX_SAFE_UPDATE_PCENT,
        delete_pcent_threshold=MAX_SAFE_DELETE_PCENT,
    ):
        self.existing = existing
        self.desired = desired
        # Sort changes to ensure we always have a consistent ordering for
        # things that make assumptions about that. Many providers will do their
        # own ordering to ensure things happen in a way that makes sense to
        # them and/or is as safe as possible.
        self.changes = sorted(changes)
        self.exists = exists
        self.update_pcent_threshold = update_pcent_threshold
        self.delete_pcent_threshold = delete_pcent_threshold

        change_counts = {'Create': 0, 'Delete': 0, 'Update': 0}
        for change in changes:
            change_counts[change.__class__.__name__] += 1
        self.change_counts = change_counts

        try:
            existing_n = len(self.existing.records)
        except AttributeError:
            existing_n = 0

        self.log.debug(
            '__init__: Creates=%d, Updates=%d, Deletes=%d Existing=%d',
            self.change_counts['Create'],
            self.change_counts['Update'],
            self.change_counts['Delete'],
            existing_n,
        )

    def raise_if_unsafe(self):
        if (
            self.existing
            and len(self.existing.records) >= self.MIN_EXISTING_RECORDS
        ):
            existing_record_count = len(self.existing.records)
            if existing_record_count > 0:
                update_pcent = (
                    self.change_counts['Update'] / existing_record_count
                )
                delete_pcent = (
                    self.change_counts['Delete'] / existing_record_count
                )
            else:
                update_pcent = 0
                delete_pcent = 0

            if update_pcent > self.update_pcent_threshold:
                raise TooMuchChange(
                    'Too many updates',
                    update_pcent * 100,
                    self.update_pcent_threshold * 100,
                    self.change_counts['Update'],
                    existing_record_count,
                    self.existing.decoded_name,
                )
            if delete_pcent > self.delete_pcent_threshold:
                raise TooMuchChange(
                    'Too many deletes',
                    delete_pcent * 100,
                    self.delete_pcent_threshold * 100,
                    self.change_counts['Delete'],
                    existing_record_count,
                    self.existing.decoded_name,
                )

        # If we have any changes of the root NS record for the zone it's a huge
        # deal and force should always be required for extra care
        if self.exists and any(
            c
            for c in self.changes
            if c.record and c.record._type == 'NS' and c.record.name == ''
        ):
            raise RootNsChange()

    def __repr__(self):
        creates = self.change_counts['Create']
        updates = self.change_counts['Update']
        deletes = self.change_counts['Delete']
        existing = len(self.existing.records)
        return (
            f'Creates={creates}, Updates={updates}, Deletes={deletes}, '
            f'Existing Records={existing}'
        )


class _PlanOutput(object):
    def __init__(self, name):
        self.name = name


class PlanLogger(_PlanOutput):
    def __init__(self, name, level='info'):
        super().__init__(name)
        try:
            self.level = {
                'debug': DEBUG,
                'info': INFO,
                'warn': WARN,
                'warning': WARN,
                'error': ERROR,
            }[level.lower()]
        except (AttributeError, KeyError):
            raise Exception(f'Unsupported level: {level}')

    def run(self, log, plans, *args, **kwargs):
        hr = (
            '*************************************************************'
            '*******************\n'
        )
        buf = StringIO()
        buf.write('\n')
        if plans:
            current_zone = None
            for target, plan in plans:
                if plan.desired.decoded_name != current_zone:
                    current_zone = plan.desired.decoded_name
                    buf.write(hr)
                    buf.write('* ')
                    buf.write(current_zone)
                    buf.write('\n')
                    buf.write(hr)

                buf.write('* ')
                buf.write(target.id)
                buf.write(' (')
                buf.write(str(target))
                buf.write(')\n*   ')

                if plan.exists is False:
                    buf.write('Create ')
                    buf.write(str(plan.desired))
                    buf.write('\n*   ')

                for change in plan.changes:
                    buf.write(change.__repr__(leader='* '))
                    buf.write('\n*   ')

                buf.write('Summary: ')
                buf.write(str(plan))
                buf.write('\n')
        else:
            buf.write(hr)
            buf.write('No changes were planned\n')
        buf.write(hr)
        buf.write('\n')

        log.log(self.level, buf.getvalue())


def _value_stringifier(record, sep):
    try:
        values = [str(v) for v in record.values]
    except AttributeError:
        values = [record.value]
    for code, gv in sorted(getattr(record, 'geo', {}).items()):
        vs = ', '.join([str(v) for v in gv.values])
        values.append(f'{code}: {vs}')
    return sep.join(values)


class PlanMarkdown(_PlanOutput):
    def run(self, plans, fh=stdout, *args, **kwargs):
        if plans:
            current_zone = None
            for target, plan in plans:
                if plan.desired.decoded_name != current_zone:
                    current_zone = plan.desired.decoded_name
                    fh.write('## ')
                    fh.write(current_zone)
                    fh.write('\n\n')

                fh.write('### ')
                fh.write(target.id)
                fh.write('\n\n')

                fh.write(
                    '| Operation | Name | Type | TTL | Value | Source |\n'
                    '|--|--|--|--|--|--|\n'
                )

                if plan.exists is False:
                    fh.write('| Create | ')
                    fh.write(str(plan.desired))
                    fh.write(' | | | | |\n')

                for change in plan.changes:
                    existing = change.existing
                    new = change.new
                    record = change.record
                    fh.write('| ')
                    fh.write(change.__class__.__name__)
                    fh.write(' | ')
                    fh.write(record.name)
                    fh.write(' | ')
                    fh.write(record._type)
                    fh.write(' | ')
                    # TTL
                    if existing:
                        fh.write(str(existing.ttl))
                        fh.write(' | ')
                        fh.write(_value_stringifier(existing, '; '))
                        fh.write(' | |\n')
                        if new:
                            fh.write('| | | | ')

                    if new:
                        fh.write(str(new.ttl))
                        fh.write(' | ')
                        fh.write(_value_stringifier(new, '; '))
                        fh.write(' | ')
                        if new.source:
                            fh.write(new.source.id)
                        fh.write(' |\n')

                fh.write('\nSummary: ')
                fh.write(str(plan))
                fh.write('\n\n')
        else:
            fh.write('## No changes were planned\n')


class PlanHtml(_PlanOutput):
    def run(self, plans, fh=stdout, *args, **kwargs):
        if plans:
            current_zone = None
            for target, plan in plans:
                if plan.desired.decoded_name != current_zone:
                    current_zone = plan.desired.decoded_name
                    fh.write('<h2>')
                    fh.write(current_zone)
                    fh.write('</h2>\n')

                fh.write('<h3>')
                fh.write(target.id)
                fh.write(
                    '''</h3>
<table>
  <tr>
    <th>Operation</th>
    <th>Name</th>
    <th>Type</th>
    <th>TTL</th>
    <th>Value</th>
    <th>Source</th>
  </tr>
'''
                )

                if plan.exists is False:
                    fh.write('  <tr>\n    <td>Create</td>\n    <td colspan=5>')
                    fh.write(str(plan.desired))
                    fh.write('</td>\n  </tr>\n')

                for change in plan.changes:
                    existing = change.existing
                    new = change.new
                    record = change.record
                    fh.write('  <tr>\n    <td>')
                    fh.write(change.__class__.__name__)
                    fh.write('</td>\n    <td>')
                    fh.write(record.name)
                    fh.write('</td>\n    <td>')
                    fh.write(record._type)
                    fh.write('</td>\n')
                    # TTL
                    if existing:
                        fh.write('    <td>')
                        fh.write(str(existing.ttl))
                        fh.write('</td>\n    <td>')
                        fh.write(_value_stringifier(existing, '<br/>'))
                        fh.write('</td>\n    <td></td>\n  </tr>\n')
                        if new:
                            fh.write('  <tr>\n    <td colspan=3></td>\n')

                    if new:
                        fh.write('    <td>')
                        fh.write(str(new.ttl))
                        fh.write('</td>\n    <td>')
                        fh.write(_value_stringifier(new, '<br/>'))
                        fh.write('</td>\n    <td>')
                        if new.source:
                            fh.write(new.source.id)
                        fh.write('</td>\n  </tr>\n')

                fh.write('  <tr>\n    <td colspan=6>Summary: ')
                fh.write(str(plan))
                fh.write('</td>\n  </tr>\n</table>\n')
        else:
            fh.write('<b>No changes were planned</b>')
