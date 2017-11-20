import argparse
import sys
from pathlib import Path
import pip.req
import devpi
import urllib
from requests import get
from os import path
from devpi import main as devpi
from devpi_common.metadata import get_sorted_versions, parse_requirement, Version
from devpi_common.viewhelp import ViewLinkStore, iter_toxresults
import tempfile
from argparse import Namespace

def options():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--origin', help='origin server, default: pypi.python.org',\
                        default='https://pypi.python.org')
    parser.add_argument('package', nargs='?', type=str, help='package to sync')
    parser.add_argument('-r', '--requirements', type=str, help='requirements list')
    parser.add_argument('-d', '--destination', help='destination server, default: pipy.example.org',\
                        default='https://pypi.example.org')
    parser.add_argument('--destination-index', help='destination index, default: root/pypi',\
                        default='root/pypi')
    parser.add_argument('--origin-index', help='origin index, default: pypi',\
                        default='pypi')
    parser.add_argument('--dest-user', help='login for auth on dest server', default='root')
    parser.add_argument('--dest-pass', help='password for auth on dest server', default='')
    parser.add_argument('--orig-user', help='login for auth on orig server')
    parser.add_argument('--orig-pass', help='password for auth on orig server')

    return parser.parse_args()

class pypisync():
    def __init__(self):
        self.pipsession = 'session'
        self.pkglist = {}

    def setup(self, opts):
        self.destination = opts.destination
        self.origin = opts.origin
        self.dst_user = opts.dest_user
        self.dst_pass = opts.dest_pass
        if opts.orig_user:
            self.orig_user = opts.orig_user
        if opts.orig_pass:
            self.orig_pass = opts.orig_pass
        if opts.requirements:
            self.requirements = opts.requirements
            self._get_req_from_file()
        if opts.package:
            pkg = pip.req.InstallRequirement.from_line(opts.package)
            if self.pkglist.get(pkg.name, False):
                print(pkg.name, "already in requirements file")
                exit(3)
            else:
                self.pkglist[pkg.name] = str(pkg.req.specifier)
        # check if our servers are reachable
        self._is_reachable(self.destination)
        self._is_reachable(self.origin)

        self.dst_index = opts.destination_index
        self.orig_index = opts.origin_index
        self.dst_url = '{}/{}'.format(self.destination, self.dst_index)
        self.orig_url = '{}/{}'.format(self.origin, self.orig_index)
        self.devpi = devpipi(self.destination, self.dst_index, self.dst_user, self.dst_pass)

    def check_presence(self):
        result = {}
        for pkg in self.pkglist:
            preq = pip.req.InstallRequirement.from_line(pkg + self.pkglist[pkg])
            versions = self._get_pkg_versions(pkg)
            valid = preq.req.specifier.filter(versions)
            if any(valid):
                result[pkg] = True
            else:
                result[pkg] = False
        return result

    def _is_reachable(self, url):
        self._check_schema(url)
        try:
            status = urllib.request.urlopen(url).getcode()
            if status not in [200, 301]:
                print('got http response:', status)
                exit(5)
        except IOError as err:
            print('error connecting to', url, 'with:')
            print(err)
            exit(5)
        return True
    def _check_schema(self, url):
        if not url.startswith('http'):
            print('please, add schema to url')
            sys.exit(4)

    def _get_req_from_file(self):
        for item in pip.req.parse_requirements(self.requirements, session=self.pipsession):
            self.pkglist[item.name] = str(item.req.specifier)

    # name - package without spec
    def _get_pkg_versions(self, name):
        l = self.devpi.get_versions_list(name)
        return l

    def _get_recent_devpi(self, pkgspec, versions, index):
        preq = pip.req.InstallRequirement.from_line(pkgspec)
        r = self.devpi._query_pkg(pkgspec, index)
        if r == None:
            return []
        valid = list(preq.req.specifier.filter(versions))
        valid = get_sorted_versions(valid)
        if len(valid) == 0:
            return []
        rdict = r.result[valid.pop()]
        result_list = []
        for i in rdict['+links']:
            if i['rel'] == 'releasefile':
                result_list.append(i['href'])
        return result_list

    def _get_recent_pypi(self, pkgspec, versions):
        preq = pip.req.InstallRequirement.from_line(pkgspec)
        r = self._query_pypi(preq.name)
        if r == None:
            return []
        valid = list(preq.req.specifier.filter(versions))
        valid = get_sorted_versions(valid)
        if len(valid) == 0:
            return []
        rdict = r['releases'][valid.pop()]
        result_list = []
        for i in rdict:
            result_list.append(i['url'])
        return result_list

    def _query_pypi(self, package, pypihost='https://pypi.python.org', index='pypi'):
        url = '{}/{}/{}/json'.format(pypihost, index, package)
        r = get(url)
        reply = r.json()
        return reply

    def _query_pypi_pkg_versions(self, pkg):
        r = self._query_pypi(pkg)
        versions_list = get_sorted_versions(r['releases'])
        return versions_list

    def sync(self):
        err = 0
        workdict = self.check_presence() # contain pkgname as key, and bool as value
        urls_to_download = {}
        for pkg in workdict:
            if not workdict[pkg]:
                fullspec = pkg + self.pkglist[pkg]
                versions = self._query_pypi_pkg_versions(pkg)
                pkg_links = self._get_recent_pypi(fullspec, versions)
                if len(pkg_links) == 0:
                    print('WARN: package {} not found in {}!'.format(pkg, self.orig_url))
                    err = 1
                else:
                    urls_to_download[pkg] = pkg_links
        if err == 1:
            print("FATAL: some packages couldn't be synchronized")
            sys.exit(1)
        with tempfile.TemporaryDirectory() as tmpdir:
            for pkg in urls_to_download:
                for link in urls_to_download[pkg]:
                    fname = tmpdir + '/' + link.split('/')[-1]
                    with open(fname, 'wb') as f:
                        response = get(link)
                        f.write(response.content)
                    self.devpi.upload(fname)

class devpipi():
    def __init__(self, host, index, user='root', passwd=''):
        self.dir = path.abspath(path.curdir)
        self.index = '{}/{}'.format(host, index)
        self.indexname = index
        self.user = user
        self.passwd = passwd
        config = [self.dir, 'use', self.index]
        parser = devpi.parse_args(config)
        self.hub = devpi.Hub(parser)
        self.hub.current.login = host + '/+login'
        self.login()

    def _query_pkg(self, pkgname, url=None):
        if url == None:
            url = self.index
        self.hub.args.spec = pkgname
        req = parse_requirement(self.hub.args.spec)
        url = self.hub.current.get_project_url(req.project_name, indexname=self.indexname)
        try:
            reply = self.hub.http_api("get", url, type="projectconfig")
        except SystemExit:
            reply = None
        return reply

    def get_versions_list(self, pkgname):
        reply = self._query_pkg(pkgname)
        if reply == None:
            return []
        return get_sorted_versions(reply.result)

    def get_urls(self, pkgname):
        reply = self._query_pkg(pkgname)

    def login(self):
        input = dict(user=self.user, password=self.passwd)
        resp = self.hub.http_api("post", self.hub.current.login, input, quiet=False)
        self.hub.current.set_auth(self.user, resp.result["password"])

    def upload(self, fname):
        f = Path(fname)
        cwd = path.abspath(path.curdir)
        res = devpi.main([cwd, 'use', self.index])
        res = devpi.main([cwd, 'login', self.user, '--password', self.passwd])
        res = devpi.main([cwd, 'upload', fname])

def main():
    opts = options()
    if not opts.package and not opts.requirements:
        print('provide package or requirements list')
        sys.exit(2)
    synctool = pypisync()
    synctool.setup(opts)
    synctool.sync()

if __name__ == '__main__':
    main()
