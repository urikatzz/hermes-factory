import json
import os
import subprocess
import sys
import unittest

from factory_copy import SCRIPTS
import factory_lib
import test_publish
from sandbox import Sandbox

ENV = dict(GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.com',
           GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.com')


def ticket(kind):
    return 'FACTORY_TICKET v2\n' + json.dumps({'PROJECT': 'game', 'TYPE': kind, 'ACCEPTANCE': 'none',
                                              'REQUEST': 'Paint the hero sprite in the approved style.'})


class TicketTests(unittest.TestCase):
    def test_structured_tickets_accept_art_only(self):
        self.assertEqual(factory_lib.parse_ticket(ticket('art'))['TYPE'], 'art')
        with self.assertRaisesRegex(ValueError, 'Invalid Factory ticket type'):
            factory_lib.parse_ticket(ticket('sound'))

    def test_ticket_cli_offers_art(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'factory_ticket.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('{feature,bug,chore,art}', result.stdout)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.repo = os.path.realpath(os.path.join(self.sb.root, 'game'))
        self.git('init', '-q', '-b', 'main', self.repo)
        with open(os.path.join(self.repo, 'README.md'), 'w') as f:
            f.write('game\n')
        self.git('-C', self.repo, 'add', 'README.md')
        self.git('-C', self.repo, 'commit', '-q', '-m', 'init')
        self.sb.write_json(self.sb.repos_path, {'default': 'game', 'repos': {
            'game': {'path': self.repo, 'base': 'main', 'auto_pr': False}}})
        # The sandbox's fake hermes answers `create` without an id; intake needs one to complete the ticket.
        fake = os.path.join(self.sb.bin, 'hermes')
        os.rename(fake, fake + '-sandbox')
        with open(fake, 'w') as f:
            f.write('#!/bin/sh\ncase " $* " in *" create "*) cat > /dev/null; echo \'{"id": "t_root0001"}\';;\n'
                    '*) exec "$0-sandbox" "$@";; esac\n')
        os.chmod(fake, 0o755)

    def git(self, *args):
        subprocess.run(['git', *args], check=True, capture_output=True, text=True, env=dict(os.environ, **ENV))

    def test_art_ticket_gets_an_art_branch(self):
        self.sb.add_task('t_art00001', 'TICKET: Paint hero', 'triage', body=ticket('art'))
        result = self.sb.run('factory_intake.py', env=ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ticket t_art00001 -> root', result.stdout)
        branches = subprocess.run(['git', '-C', self.repo, 'branch', '--list', 'art/*', '--format=%(refname:short)'], capture_output=True,
                                  text=True).stdout.split()
        self.assertEqual(branches, ['art/paint-hero'])


class PublishTests(unittest.TestCase):
    def test_art_jobs_publish_with_a_feat_art_title(self):
        base = test_publish.PublishTests('test_passing_writer_gate_opens_a_draft_pr_with_only_manifest_files')
        base.setUp()
        self.addCleanup(base.tearDown)
        root = base.sb.tasks[0]
        root['body'] = root['body'].replace('TYPE: feature', 'TYPE: art')
        base.register_repo('true')
        result = base.sb.run('factory_publish.py', env={'GIT_CONFIG_NOSYSTEM': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('| feat(art): say hello', result.stdout)
