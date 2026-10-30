#!/bin/zsh
cd -- "${0:A:h}"
/usr/bin/caffeinate -i /usr/bin/python3 web_server.py
