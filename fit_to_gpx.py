#!/usr/bin/env python3

'''This script converts a list of FIT-formatted files given on the command line
into GPX-formatted files. The FIT file can be gzipped.'''

import contextlib
import gzip
import re
import argparse

import fitparse

XML_HEADER = '''<?xml version='1.0' encoding='us-ascii'?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" creator="Greg Hamerly w/fitparse" version="1.1" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
<trk>
  <name>{activity_name}</name>
  <time>{time_created}</time>
<trkseg>
'''

XML_TRKPT = '<trkpt lat="{position_lat}" lon="{position_long}"><time>{timestamp}</time></trkpt>\n'

XML_FOOTER = '''</trkseg>
</trk>
</gpx>
'''

def semicircles_to_degrees(semi):
    '''Convert an angle given in semicircles into degrees.'''
    return semi * 180 / (2 ** 31)

def get_values(record, *field_names):
    '''Convenience function to parse through a data record in a FIT file and
    extract just the values of those named fields, as a dictionary.'''
    results = {x.name: x.value for x in record if x.name in field_names}
    if len(results) != len(field_names):
        return None
    return results

@contextlib.contextmanager
def open_file(input_filename):
    '''Open a file either as binary, or gzipped data, depending on filename. Can
    be used in a context.'''
    file_obj = None
    if input_filename.endswith('.gz'):
        file_obj = gzip.open(input_filename)
    else:
        file_obj = open(input_filename, 'rb')

    try:
        yield file_obj
    finally:
        file_obj.close()

def convert_to_gpx(fitobj):
    '''Convert a FIT object which has been parsed into a GPX-formatted
    string.'''
    track = []
    missing = total = 0
    for record in fitobj.get_messages('record'):
        trkpt_data = get_values(record, 'position_lat', 'position_long', 'timestamp')

        total += 1

        if not trkpt_data:
            missing += 1
            continue

        trkpt_data['position_lat'] = semicircles_to_degrees(trkpt_data['position_lat'])
        trkpt_data['position_long'] = semicircles_to_degrees(trkpt_data['position_long'])
        track.append(trkpt_data)

    record = get_values(list(fitobj.get_messages('file_id'))[0], 'time_created')
    time_created = record['time_created']
    activity_name = 'Run {}'.format(time_created)

    if missing:
        print('could not parse {}/{} track points'.format(missing, total))

    if not track:
        return time_created, None

    output = [
        XML_HEADER.format(activity_name=activity_name, time_created=time_created),
        ''.join(XML_TRKPT.format(**p) for p in track),
        XML_FOOTER
        ]

    return time_created, ''.join(output)

def main():
    '''Given a list of file names on the command line, parse each of them as FIT
    files and then export them to GPX-formatted files, named according to their
    timestamps.'''

    parser = argparse.ArgumentParser()
    parser.add_argument('gpx_file', nargs='+')
    args = parser.parse_args()

    for input_filename in args.gpx_file:
        print('processing', input_filename)
        with open_file(input_filename) as input_file:
            fitobj = fitparse.FitFile(input_file)
            fitobj.parse()

        time_created, gpx_data = convert_to_gpx(fitobj)

        if not gpx_data:
            print('no track data for {}; skipping'.format(input_filename))
            continue

        output_filename = re.sub('[^-a-z_0-9.]', '_',
                                 'converted_from_fit_{}.gpx'.format(time_created))
        with open(output_filename, 'w') as out:
            out.write(gpx_data)

if __name__ == '__main__':
    main()
