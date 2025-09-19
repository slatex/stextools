"""
HTML support for steppers.

Using html.parser from the standard library because
we can get source references with it.
Unlike, e.g. from an lxml DOM.

The whole thing is rather hacky (a DOM solution would be cleaner).
"""
from html import unescape
from html.parser import HTMLParser
from typing import Optional

from stextools.utils.linked_str import string_to_lstr, LinkedStr, fixed_range_lstr, concatenate_lstrs


class MyHtmlParser(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.text = text

        self.body_start: Optional[int] = None
        self.body_end: Optional[int] = None
        self.annotatable_plaintext_ranges: list[LinkedStr[None]] = []

        self.tag_stack: list[str] = []
        # the generation of annotatable plaintext segments can be blocked,
        # (e.g. inside the <head> tag)
        # we store a depth to know when it can be resumed
        # if the depth is None, we can generate annotatable plaintext segments
        self.resume_depth: Optional[int] = None


        self.line_no_to_offset: list[int] = [0]
        value = 0
        for line in text.splitlines(keepends=True):
            value += len(line)
            self.line_no_to_offset.append(value)

    def get_offset(self):
        p = self.getpos()
        return self.line_no_to_offset[p[0]-1] + p[1]

    def handle_starttag(self, tag, attrs):
        if self.resume_depth is None:
            if tag in {'head', 'script', 'style', 'math', 'svg'}:
                self.resume_depth = len(self.tag_stack)
        self.tag_stack.append(tag)
        if tag == 'body' and self.body_start is None:
            self.body_start = self.get_offset()
            while self.body_start < len(self.text) and self.text[self.body_start] != '>':
                self.body_start += 1
            self.body_start += 1


    def handle_endtag(self, tag):
        while self.tag_stack.pop() != tag:
            pass
        if self.resume_depth is not None and len(self.tag_stack) <= self.resume_depth:
            self.resume_depth = None
        if tag == 'body' and self.body_end is None:
            self.body_end = self.get_offset() - 1

    def handle_data(self, data):
        if self.resume_depth is not None:
            return
        # we have annotatable plaintext here
        # and thanks to escaping, it's a bit messy

        start = self.get_offset()
        text = self.text
        end = start
        # data is already unescaped, so possibly end - start != len(data)
        while end < len(text) and text[end] != '<':
            end += 1
        raw_data = text[start:end]
        if not raw_data.strip():
            return

        # now we have to turn raw_data into an (unescaped) LinkedStr
        i = 0
        lstrs = []
        while i < len(raw_data):
            if raw_data[i] == '&':
                stop = raw_data.find(';', i+1)
                if stop == -1:
                    # something is wrong - should we raise an error?
                    lstrs.append(string_to_lstr(raw_data[i], start + i))
                    i += 1
                else:
                    entity = raw_data[i:stop+1]
                    unescaped = unescape(entity)
                    lstrs.append(fixed_range_lstr(unescaped, start + i, stop + 1))
                    i = stop + 1
            else:
                lstrs.append(string_to_lstr(raw_data[i], start + i))
                i += 1

        self.annotatable_plaintext_ranges.append(concatenate_lstrs(lstrs, None))

# from pathlib import Path
# html = Path('test.html').read_text()
# parser = MyHtmlParser(html)
# parser.feed(html)
