#!/usr/bin/env python2

import sys, re, datetime, time, os

def parse(f):
    data = f.read()

    # Strip comments and blank lines
    data = re.sub(r"(?m)^#.*", "", data)
    data = re.sub(r"(?m)^\n", "", data)

    # Break in to logical lines
    lines = re.split(r"(?m)^(- .*(?:\n  .*)*|\{\{(?:.|\n)*?\}\}|.*)\n?", data)
    lines = filter(None, lines)

    # Parse lines and generate output
    cal = prevDate = minPrevDate = None
    dp = DateParser()
    layerDates = set()
    for line in lines:
        m = re.match("([A-Za-z0-9]+)\s*=\s*(.+)", line)
        if m:
            # Date definition
            dp.env[m.group(1)] = dp.parse(m.group(2), prevDate)
        elif line.startswith("== "):
            # Layer
            if not line.endswith(" =="):
                raise ValueError("Unmatched ==")
            if cal:
                cal.restart()
            prevDate = minPrevDate
            layerDates = set()
            dp.env[line[2:-2].strip()] = lambda q, ds=layerDates: q in ds
        elif line.startswith("- "):
            # Item
            line = line.replace("\n  ", " ")
            m = re.match(r"- ([A-Z][A-Za-z]*)(?:\s+([^:]*))?(?::\s+(.*))?", line)
            if not m:
                raise ValueError("Failed to parse entry %r" % line)
            if not cal:
                raise ValueError("Entry without date %r" % line)
            args = {}
            if m.group(2): args["extra"] = m.group(2)
            if m.group(3): args["text"] = m.group(3)
            getattr(cal, m.group(1))(**args)
        elif line.startswith("{{"):
            # Raw HTML
            if not line.endswith("}}"):
                raise ValueError("Unmatched {{")
            if cal:
                cal.write()
                cal = None
            print(line[2:-2])
        else:
            # Must be a date or date range
            d = [dp.resolve(s, prevDate) for s in line.split("-", 1)]
            if minPrevDate:
                minPrevDate = min(minPrevDate, d[-1])
            else:
                minPrevDate = d[-1]
            prevDate = d[-1] + datetime.timedelta(1)
            if not cal:
                cal = CalWriter()
            cal.date(d[0], d[-1])
            # Add to layer date set
            ld = d[0]
            while ld <= d[-1]:
                layerDates.add(ld)
                ld += datetime.timedelta(1)
    if cal: cal.write()

class DateParser(object):
    def __init__(self):
        self.env = {}
        for i, n in enumerate(["Mon", "Tue", "Wed", "Thr", "Fri", "Sat", "Sun"]):
            self.env[n] = lambda q, i=i: q.weekday() == i

    def parse(self, s, dot):
        self.__str, self.__pos = s.rstrip(), 0
        self.__dot = dot
        res = self.__expr()
        if self.__pos != len(s.rstrip()):
            raise ValueError("Syntax error: %r" % s)
        return res

    def resolve(self, s, minDate):
        self.__str, self.__pos = s.rstrip(), 0
        date = self.__abs()
        if date and self.__pos == len(s.rstrip()):
            return date
        if minDate is None:
            raise ValueError("First date must be absolute: %r" % s)
        pred = self.parse(s, minDate)
        for tries in range(100):
            if pred(minDate):
                return minDate
            minDate += datetime.timedelta(1)
        raise ValueError("Unresolvable date: %r (from %s)" % (s, minDate))

    def __c(self, regexp):
        self.__m = re.compile(r"\s*(?:" + regexp + ")").match(self.__str, self.__pos)
        if self.__m:
            self.__pos = self.__m.end()
        return self.__m

    def __expr(self):
        if self.__c(r"\bnot\b"):
            f = self.__expr()
            return lambda q: not f(q)
        return self.__and()

    def __and(self):
        l = self.__or()
        r = self.__expr() if self.__c(r"\band\b") else lambda q: True
        return lambda q: l(q) and r(q)

    def __or(self):
        l = self.__term()
        r = self.__expr() if self.__c(r"\bor\b") else lambda q: False
        return lambda q: l(q) or r(q)

    def __term(self):
        if self.__c(r"\("):
            l = self.__expr()
            if not self.__c(r"\)"):
                raise ValueError("Unbalanced paren: %r" % self.__str)
            return l
        absDate = self.__abs()
        if absDate:
            return lambda q: q == absDate
        if self.__c(r"\b([A-Za-z0-9]+)\b"):
            if self.__m.group(1) in self.env:
                return self.env[self.__m.group(1)]
            raise ValueError("Unknown date set: %r" % self.__m.group(1))
        if self.__c(r"^\.$"):
            dot = self.__dot
            return lambda q: q == dot
        raise ValueError("Syntax error: %r" % self.__str)

    def __abs(self):
        if self.__c(r"\b([A-Za-z]{3} [0-9]+, [0-9]+)\b"):
            return datetime.datetime.strptime(self.__m.group(1), "%b %d, %Y").date()

style_order = ['lecture', 'recitation', 'tutorial',
               'quiz',
               'prep', 'due', 'assign',
               'important',
               'special', 'holiday',
               None]

class CalWriter(object):
    def __init__(self):
        self.__items = []
        self.restart()

    def restart(self):
        self.__start = self.__end = None
        self.__lec = 1
        self.__rec = 1
        self.__tut = 1

    def date(self, start, end):
        if self.__end and start < self.__end:
            raise ValueError("Date %r is out of order" % start)
        self.__start, self.__end = start, end

    def write(self):
        self.__items.sort(key = lambda item: (item['start'],
                                              style_order.index(item['style'])))

        # Round start date down to a Monday
        date = self.__items[0]['start']
        date = date - datetime.timedelta(date.weekday())

        while self.__items:
            while date < self.__items[0]['start']:
                date = self.__emit(date, date, None, [])

            # Merge items in the same range
            item = self.__items.pop(0)
            start, end, style, html = (item['start'], item['end'],
                                       item['style'], item['html'])
            while self.__items and self.__items[0]['start'] <= end:
                item2 = self.__items.pop(0)
                start2, end2, style2, html2 = (item2['start'], item2['end'],
                                               item2['style'], item2['html'])
                if start != start2 or end != end2:
                    raise ValueError(
                        "Overlapping date ranges: %s-%s and %s-%s" %
                        (start, end, start2, end2))
                style = self.__mergeStyles(style, style2)
                html = html + html2

            # Emit merged items
            date = self.__emit(start, end, style, html)

        # Finish out the last week
        while date.weekday() != 0:
            date = self.__emit(date, date, None, [])

    def __mergeStyles(self, s1, s2):
        if style_order.index(s1) < style_order.index(s2):
            return s1
        return s2

    def __emit(self, d, end, style, html):
        # Format the date or date range
        s = d.strftime("%b %e").replace("  ", " ").lower()
        span = (end - d).days + 1
        if span != 1:
            s += " - " + end.strftime("%b %e").replace("  ", " ").lower()

        if d.weekday() == 0:
            print("<tr> <!-- week of %s -->" % s)
        if d.weekday() < 5:
            # Emit the table cell
            attr = 'id="%d-%d-%d"' % (d.year, d.month, d.day)
            if style:
                attr += ' class="%s"' % style
            if span != 1:
                attr += ' colspan="%d"' % span
            c = "".join("<br />\n    " + l for l in html)
            print('  <td %s><span class="date">%s</span>%s</td>' % (attr, s, c))
        if d.weekday() == 6:
            print("</tr>")
        return end + datetime.timedelta(1)

    def item(self, text = None, style = None):
        if text:
            html = [re.sub(r"(?s)\[(\S*)(?:\s*(.*?))\]", r'<a href="\1">\2</a>', text)]
        else:
            html = []
        d = self.__start
        while d <= self.__end:
            self.__items.append({'start': d, 'end': d, 'style': style, 'html': html})
            d = d + datetime.timedelta(1)

    def Text(self, text, extra = None):
        self.item(text, extra)

    def Holiday(self, text = None): self.item(text, "holiday")

    def Special(self, text = None): self.item('<i>' + text + '</i>', "special")

    def Lec(self, text = None, extra = None):
        if extra is None:
            lecturer = ''
        else:
            lecturer = ' (%s)' % extra
        self.item("<b>LEC %d%s:</b> %s" % (self.__lec, lecturer, text), "lecture")
        self.__lec += 1

    def Rec(self, text):
        self.item("<b>REC %d:</b> %s" % (self.__rec, text), "recitation")
        self.__rec += 1

    def Tut(self, text):
        self.item("<b>TUT %d:</b> %s" % (self.__tut, text), "tutorial")
        self.__tut += 1

    def Prep(self, text = None, extra = None):
        preptext = ''
        if text is not None:
            preptext += ' %s' % text
        if extra is not None:
            # HACK: self.__lec contains the next lecture number, so subtract 1.
            #preptext += (' (<a href="questions.html?q=q-%s&amp;lec=%d">Question</a>)' %
            #             (extra, self.__lec - 1))
            pass
        self.item('<span class="reading"><b>Preparation:</b> %s</span>' % preptext, 'prep')

    def Assign(self, text):
        self.item('<span class="reading"><b>Assigned:</b> %s</span>' % text, 'assign')

    def Due(self, text):
        self.item('<span class="deadline"><b>DUE:</b> %s</span>' % text, 'due')

parse(open("schedule.in"))
