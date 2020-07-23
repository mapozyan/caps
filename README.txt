Calibre Power Search Plugin
===========================

Version 1.0.0, released on 23 Jul 2020. Created by Michael Apozyan

Overview
--------

This plugin enables full-text search functionality to your electronic library. Default shortcut key
for Power Search dialog is Ctrl+Shift+S.
When you run Power Search, it extracts text from all your books on the fly and sends all text to the
full-text search engine. Plugin will never modify any books and records in Calibre library. As a
search backend, we are using ElasticSearch. Once the index is created and is up-to-date, Power Search
is querying search engine and displaying list of books where certain search keywords were found.
For large libraries, running search for the first time might take a while. Subsequent searches though
will normally take less than a second.

Requirements
------------

* ElasticSearch >= 6.x
    In order to use Power Search Plugin you need to have ElasticSearch service up and running.
    Please follow the instructions provided on the official website to install it:
    https://www.elastic.co/guide/en/elasticsearch/reference/current/getting-started-install.html


* Pdftotext utility (optional)
    Generally, Power Search Plugin is using Calibre's native converters to build full-text index.
    However, native PDF conversion is sometimes working too slow. To speed up this process, you can
    install pdftotext utility and plugin will make use of it. Pdftotext is part of Xpdf and Poppler
    projects. Specifically for Debian/Ubuntu check for 'xpdf' or 'libpoppler73' apt packages.

Configuring
-----------

* ElasticSearch engine location
    If you installed ElasticSearch locally, it will usually be available at http://localhost:9200/
    so you don't need to modify this setting. However, you can change it if you need different setup. 

* Path to pdftotext tool
    If pdftotext tool can not be found in PATH, enter the full path to pdftotext.

* Number of parallel processes for text extraction
    By default this number is equal to number of CPUs on your system. You can change it if neccessary.

Feedback
--------

For bug reports and feature requests please contact mapozyan (at) yahoo.com
