#!/usr/bin/python
import pystache
import sys

def usage():
    print("usage: gen.py <page>")

if len(sys.argv) < 2:
    usage()
    sys.exit(1)

path = sys.argv[1]
pathbits = path.split('/')
page = pathbits[0]
relative_root = ""
for i in range(len(pathbits) - 1):
    relative_root += "../"

context = {}
context['ROOT'] = relative_root
context['{}_ACTIVE'.format(page)] = 'active';
context["NAVBAR"] = pystache.render(open("navbar.tmpl").read(), context)
context["MAIN"] = pystache.render(open("{}.tmpl".format(path)).read())

template = open("top.tmpl").read()
print(pystache.render(template, context))
