#!/usr/bin/env python3

'''This script combines and simplifies all the given GPX files into one GPX
file. It's built to work on exported GPX files from RunKeeper. It has also
worked on data from Strava.

This script has two primary purposes:
    1. Combine many GPX files into one (with separate tracks) so that the one
    file can be uploaded / visualized.

    2. Remove / filter waypoints and/or data that we don't need, in order to
    save space. In my testing, this regularly saves about 90%. The purpose for
    this is not only quick loading/rendering, but also because some services
    have space limits on file upload sizes.

As an example of the data this script works on, this is an edited version of a
GPX file exported from RunKeeper:

    <?xml version="1.0" encoding="UTF-8"?>
    <gpx
      version="1.1"
      creator="Runkeeper - http://www.runkeeper.com"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns="http://www.topografix.com/GPX/1/1"
      xsi:schemaLocation="http://www.topografix.com/GPX/1/1
                          http://www.topografix.com/GPX/1/1/gpx.xsd"
      xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
    <trk>
      <name><![CDATA[Running 4/13/20 6:58 am]]></name>
      <time>2020-04-13T11:58:19Z</time>
    <trkseg>
    <trkpt lat="27.806221000" lon="-100.935776000">
        <ele>188.2</ele><time>2020-04-13T11:58:19Z</time></trkpt>
    <trkpt lat="27.806253000" lon="-100.935881000">
        <ele>188.3</ele><time>2020-04-13T11:58:23Z</time></trkpt>
    <trkpt lat="27.806169000" lon="-100.935909000">
        <ele>188.4</ele><time>2020-04-13T11:58:29Z</time></trkpt>
    [snip]
    </trkseg>
    </trk>
    </gpx>

TODO -- things to improve this script:
    - Try the RamerDouglasPeucker polyline simplification algorithm
      https://en.wikipedia.org/wiki/Ramer%E2%80%93Douglas%E2%80%93Peucker_algorithm

    - Look at the GPX format and determine if we are in compliance or need to
      adapt:
      - https://www.topografix.com/gpx.asp
      - https://en.wikipedia.org/wiki/GPS_Exchange_Format

    - Reduce the hackiness around the XML namespacing. I didn't really know the
      best way to fix this.

    - Raise the representation from raw XML into something with more
      flexibility that can import from XML, be modified, and then export to XML
      (but only if that type of flexibility becomes needed and beneficial).
'''

import argparse
import math
import xml.etree.ElementTree


EARTH_RADIUS_MILES = 3958.756
EARTH_RADIUS_KILOMETERS = 6371

def haversine(lon1, lat1, lon2, lat2, earth_radius=EARTH_RADIUS_MILES):
    '''Compute great circle distances using the Haversine formulation; see:
    https://en.wikipedia.org/wiki/Haversine_formula
    '''
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    sin, cos = math.sin, math.cos
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * earth_radius * math.asin(math.sqrt(hav))

def _remove_all(parent, child):
    '''Function that simply removes the child XML element from the parent.'''
    parent.remove(child)

def _iterate_over(segment, search, functor):
    '''Generic function to walk over tree the entire tree "segment", looking for
    tags that have the name "search", and applying "functor" for each match.

    If the functor ever returns False, then stop early. '''
    for parent in segment.getiterator():
        for child in parent.findall('{http://www.topografix.com/GPX/1/1}' + search):
            result = functor(parent, child)
            if result is False:
                return

def sum_segment_distance(segment):
    '''Sum the distance along a segment using the Haversine formula. Assumes
    miles.'''

    total_distance = 0
    last = None, None

    def _sum_functor(_, child):
        nonlocal total_distance, last
        lat1, lon1 = last
        lat2, lon2 = latlon(child)
        if lat1 is not None:
            total_distance += haversine(lon1, lat1, lon2, lat2)
        last = (lat2, lon2)

    _iterate_over(segment, 'trkpt', _sum_functor)

    return total_distance

def latlon(waypt):
    '''Split an XML waypoint into a (lat, lon) pair.'''
    return float(waypt.attrib['lat']), float(waypt.attrib['lon'])

def cross(p_a, p_b, p_c):
    '''Compute the cross product of the angle connecting a->b->c.

    Here a, b, c are XML elements that have lat & lon attributes.'''

    a_lat, a_lon = latlon(p_a)
    b_lat, b_lon = latlon(p_b)
    c_lat, c_lon = latlon(p_c)

    a_b = [b_lat - a_lat, b_lon - a_lon]
    b_c = [c_lat - b_lat, c_lon - b_lon]

    return a_b[0] * b_c[1] - a_b[1] * b_c[0]

def dot(p_a, p_b, p_c):
    '''Compute the dot product of the angle connecting a->b->c.

    Here a, b, c are XML elements that have lat & lon attributes.'''

    a_lat, a_lon = latlon(p_a)
    b_lat, b_lon = latlon(p_b)
    c_lat, c_lon = latlon(p_c)

    a_b = [b_lat - a_lat, b_lon - a_lon]
    b_c = [c_lat - b_lat, c_lon - b_lon]

    return a_b[0] * b_c[0] + a_b[1] * b_c[1]

def linearize(segment, tol):
    '''Simple approach for removing points from a segment that are linear with
    respect to their successor and predecessor. Maintains a stack of points seen
    (path) and then repeatedly compares the new point to the most recently-added
    point, removing the latter if possible. Similar in flavor to Graham's
    scan.'''

    path = []
    count = 0

    def _f(parent, child):
        nonlocal path, count
        while len(path) >= 2 and \
            dot(path[-2][1], path[-1][1], child) > 0 and \
            abs(cross(path[-2][1], path[-1][1], child)) <= tol:
            path_parent, current = path.pop()
            path_parent.remove(current)

        count += 1
        path.append((parent, child))

    _iterate_over(segment, 'trkpt', _f)

    if len(path) != count:
        print('linearize: kept', len(path), 'out of', count)

def keepevery(segment, k):
    ''' Very simple and crude filter, keep only every k'th waypoint.'''
    count = removed = 0

    def _f(parent, child):
        nonlocal count, removed
        count += 1
        if count % k:
            parent.remove(child)
            removed += 1

    _iterate_over(segment, 'trkpt', _f)

    if removed:
        print('subsample removed', removed, '/', count)

def filterlatlon(segment, latrange, lonrange):
    '''Only keep points that are within the given latitude and longitude
    ranges.'''

    minlat, maxlat = latrange
    minlon, maxlon = lonrange
    count = removed = 0

    def _f(parent, child):
        nonlocal minlat, maxlat, minlon, maxlon
        nonlocal count, removed
        lat = float(child.attrib['lat'])
        lon = float(child.attrib['lon'])
        count += 1
        if not (minlat <= lat <= maxlat and minlon <= lon <= maxlon):
            removed += 1
            parent.remove(child)

    _iterate_over(segment, 'trkpt', _f)
    if removed:
        print('lat/lon filter removed', removed, 'of', count, 'waypoints')

def striptime(segment):
    '''Remove every "time" tag.'''
    _iterate_over(segment, 'time', _remove_all)

def stripextensions(segment):
    '''Remove every "extensions" tag.'''
    _iterate_over(segment, 'extensions', _remove_all)

def stripelevation(segment):
    '''Remove every "ele" tag.'''
    _iterate_over(segment, 'ele', _remove_all)

def striptrailingzeros(segment):
    '''Remove trailing zeros from lat/lon values.'''
    def _f(_, child):
        child.attrib['lat'] = child.attrib['lat'].rstrip('0')
        child.attrib['lon'] = child.attrib['lon'].rstrip('0')
    _iterate_over(segment, 'trkpt', _f)

def empty(segment):
    '''Determine whether or not a segment has any waypoints.'''

    no_trkpts = True

    def _f(_, __):
        nonlocal no_trkpts
        no_trkpts = False
        return False # stop looking, we found a trkpt

    _iterate_over(segment, 'trkpt', _f)

    return no_trkpts

def main():
    '''Read in a number of GPX files named on the command line, filter and
    simplify them, and combine them into one output.'''

    # this is to fix the output namespace at the end -- see
    # https://stackoverflow.com/a/18340978
    xml.etree.ElementTree.register_namespace('', 'http://www.topografix.com/GPX/1/1')

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('gpxfile', nargs='+')
    parser.add_argument('--out', default='combined.gpx')

    filter_group = parser.add_argument_group('Filters on what is kept')
    filter_group.add_argument('--keepevery', type=int, default=1,
                              help='Keep 1/N of all track points')
    filter_group.add_argument('--nolinearize', dest='linearize', action='store_false', default=True,
                              help="Don't discard intermediate linear points (uses tolerance)")
    filter_group.add_argument('--linearizetol', type=float, default=1.5e-8,
                              help='Tolerance for linearization (smaller = keep more points)')
    filter_group.add_argument('--striptime', action='store_true', default=False,
                              help='Remove timestamps')
    filter_group.add_argument('--nostripelevation', dest='stripelevation', action='store_false',
                              default=True, help='Do not remove elevation')
    filter_group.add_argument('--nostriptrailingzeros', dest='striptrailingzeros',
                              action='store_false', default=True,
                              help='Do not strip trailing zeros from lat/long')
    filter_group.add_argument('--nostripextensions', dest='stripextensions', action='store_false',
                              default=True, help='Do not strip "extension" tag data')
    filter_group.add_argument('--latrange', nargs=2, type=float, default=[31, 32])
    filter_group.add_argument('--lonrange', nargs=2, type=float, default=[-98, -97])

    args = parser.parse_args()

    # use the first file as the master tree, and append tracks to it
    master_tree = None

    total_distance = 0

    for gpx_file in sorted(args.gpxfile):
        print('processing', gpx_file)
        tree = xml.etree.ElementTree.parse(gpx_file)

       # Runkeeper-specific filter on runs (as opposed to bike rides, etc.);
       # Commented out because it does not work for other sources (e.g. strava).
       # Need to generalize this concept.
       #name = tree.iter('{http://www.topografix.com/GPX/1/1}name')
       #if not name:
       #    continue
       #name = next(name)
       #if not name.text.startswith('Running'):
       #    continue
        for segment in tree.iter('{http://www.topografix.com/GPX/1/1}trk'):
            keepevery(segment, args.keepevery)

            if args.linearize:
                linearize(segment, args.linearizetol)

            filterlatlon(segment, args.latrange, args.lonrange)

            if args.striptime:
                striptime(segment)
            if args.stripelevation:
                stripelevation(segment)
            if args.striptrailingzeros:
                striptrailingzeros(segment)
            if args.stripextensions:
                stripextensions(segment)

            if not empty(segment):
                segment_distance = sum_segment_distance(segment)
                total_distance += segment_distance
                print('segment distance {:0.1f} miles'.format(segment_distance))
                if master_tree:
                    master_tree.getroot().append(segment)
                else:
                    master_tree = tree

    print('total distance {:0.1f} miles'.format(total_distance))

    with open(args.out, 'wb') as out:
        master_tree.write(out, xml_declaration=True)

if __name__ == '__main__':
    main()
