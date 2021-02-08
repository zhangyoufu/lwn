#!/usr/bin/env python3
from contextlib import contextmanager
from dataclasses import dataclass
import datetime
import os
import re
import requests
import sys
import time

HTTP_RETRY_INTERVAL = 60
STATE_FILENAME = 'state/articles.txt'
RSS_FILENAME = 'gh-pages/rss.rdf'

def http_get(url, expect=(200,), **kwargs):
    print('GET', url)
    kwargs.setdefault('allow_redirects', False)
    while 1:
        try:
            rsp = requests.get(url, **kwargs)
            if rsp.status_code not in expect:
                raise RuntimeError
            return rsp
        except Exception:
            time.sleep(HTTP_RETRY_INTERVAL)

month_idx = {k: v+1 for v,k in enumerate('January|February|March|April|May|June|July|August|September|October|November|December'.split('|'))}

# TODO: verify whether the actual unlock time is 00:00 UTC
def get_avail_date(article_id, date):
    rsp = http_get(f'https://lwn.net/Articles/{article_id}/', expect=(200, 403))
    if rsp.status_code == 200:
        return date
    m = re.search(r'available on (?P<month>January|February|March|April|May|June|July|August|September|October|November|December) (?P<day>[1-9]|[12][0-9]|3[01]), (?P<year>\d{4,})', rsp.text)
    return datetime.datetime(
        year = int(m.group('year')),
        month = month_idx[m.group('month')],
        day = int(m.group('day')),
        tzinfo = datetime.timezone.utc,
    )

def get_date(articles, ref={}):
    for article in articles:
        raw = article.raw
        m = re.search(r'(?s)<title>(?P<dollar>\[\$\] )?.*?<dc:date>(?P<date>[^<]+)</dc:date>', raw)
        dollar = m.group('dollar') is not None
        date = datetime.datetime.fromisoformat(m.group('date'))
        if dollar:
            date = ref.get(article.id, None) or get_avail_date(article.id, date)
            article.raw = ''.join((
                raw[:m.start('dollar')],
                raw[m.end('dollar'):m.start('date')],
                date.isoformat(),
                raw[m.end('date'):],
            ))
        article.date = date

@dataclass(init=False)
class Article:
    date: datetime.datetime
    id: int
    raw: str

# BUG: assume there is no multiple '[$] ' prefix in title
def load(data):
    articles = []
    for m in re.finditer(r'(?ms)^\s*<item rdf:about="https://lwn\.net/Articles/(?P<article_id>\d+).*?</item>', data):
        article = Article()
        article.id = int(m.group('article_id'))
        article.raw = m.group()
        articles.append(article)
    return articles

def load_from(filename):
    try:
        with open(filename, encoding='utf-8-sig') as f:
            return load(f.read())
    except FileNotFoundError:
        return []

local = load_from(STATE_FILENAME)
get_date(local)
id_set = set(article.id for article in local)
date_dict = {article.id: article.date for article in local}

remote = load(http_get('https://lwn.net/headlines/rss').text.replace('/rss</link>', '/</link>'))
remote = list(filter(lambda article: article.id not in id_set, remote))
get_date(remote, ref=date_dict)

items = remote + local
items = sorted(items, key=lambda article: article.date, reverse=True)

now = datetime.datetime.now(tz=datetime.timezone.utc)

count = 20
local = []
for article in items:
    if article.date <= now:
        # this article is freely available
        if count <= 0:
            # too many free articles, discard
            continue
        count -= 1
    local.append(article)

publish = list(filter(lambda article: article.date < now, local))

linesep = '\n'
rss = f'''\
<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
  xmlns="http://purl.org/rss/1.0/"
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:syn="http://purl.org/rss/1.0/modules/syndication/"
  xmlns:atom="http://www.w3.org/2005/Atom"
>
  <channel rdf:about="{os.environ['FEED_URL']}">
    <title>LWN.net</title>
    <link>https://lwn.net</link>
    <description>
      LWN.net is a comprehensive source of news and opinions from
      and about the Linux community. This is the main LWN.net feed,
      listing all articles which are posted to the site front page.
    </description>
    <syn:updatePeriod>hourly</syn:updatePeriod>
    <syn:updateFrequency>6</syn:updateFrequency>
    <atom:link rel="self" href="{os.environ['FEED_URL']}" />
    <atom:link rel="hub" href="{os.environ['HUB_URL']}" />
    <items>
      <rdf:Seq>
{linesep.join(f'        <rdf:li resource="https://lwn.net/Articles/{article.id}/rss" />' for article in publish)}
      </rdf:Seq>
    </items>
  </channel>
{linesep.join(article.raw for article in publish)}
</rdf:RDF>
'''

with open(STATE_FILENAME, 'w', encoding='utf-8-sig') as f:
    f.write('\n'.join(article.raw for article in local))
    f.truncate()

with open(RSS_FILENAME, 'w') as f:
    f.write(rss)
    f.truncate()
