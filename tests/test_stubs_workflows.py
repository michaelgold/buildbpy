"""Execute the real workflow shell steps, not a copy of their version logic."""
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())


def step(name, step_id):
    return next(s for s in workflow(name)['jobs']['check-version']['steps'] if s.get('id') == step_id)


def execute(step, values, tmp_path):
    script = step['run']
    for key, value in values.items():
        script = script.replace('${{ ' + key + ' }}', value)
    assert '${{' not in script
    output = tmp_path / 'outputs'
    output.write_text('')
    subprocess.run(['bash', '-e', '-c', script], check=True, cwd=ROOT,
                   env={**os.environ, 'GITHUB_OUTPUT': str(output)})
    return dict(line.split('=', 1) for line in output.read_text().splitlines())


@pytest.mark.parametrize('tag,expected', [
    ('v3.6.0', '3.10.11'), ('v4.0.2', '3.10.11'),
    ('v4.1.0', '3.11.9'), ('v4.5.0', '3.11.9'), ('v5.0.0', '3.11.9'),
    ('v5.1.0', '3.13.11'), ('v5.2.3', '3.13.11'), ('v6.0.0', '3.13.11'),
])
def test_stubs_and_wheels_select_compatible_python(tag, expected, tmp_path):
    for name in ('build_stubs.yml', 'build_all.yml'):
        result = execute(step(name, 'set_python_version'),
                         {'steps.set_tag_input.outputs.tag_input': tag}, tmp_path)
        assert result['python_version'] == expected, name


@pytest.mark.parametrize('explicit,latest,new_tag,expected', [
    ('v4.1.0', 'v5.2.3', 'false', 'v4.1.0'),
    ('', 'v5.2.3', 'true', 'v5.2.3'),
    ('', 'v5.2.3', 'false', 'v5.2.3'),
    ('', '', 'false', None),
])
def test_stubs_do_not_use_wheel_completion_state(explicit, latest, new_tag, expected, tmp_path):
    result = execute(step('build_stubs.yml', 'set_tag_input'), {
        'github.event.inputs.tag': explicit,
        'steps.check.outputs.latest_tag': latest,
        'steps.check.outputs.new_tag': new_tag,
        'steps.check.outputs.new_commit': 'false',
    }, tmp_path)
    assert result.get('tag_input') == expected


def test_version_check_uses_tracked_workspace():
    check = step('build_stubs.yml', 'check')
    assert check['working-directory'] == 'workspace'
    assert check['run'] == 'python check_latest.py'


def test_generator_runner_actions_and_output_contract():
    job = workflow('generate_stubs.yml')['jobs']['build']
    assert job['runs-on'] == 'ubuntu-24.04'
    for s in job['steps']:
        if s.get('uses', '').startswith(('actions/checkout@', 'actions/setup-python@')):
            assert re.fullmatch(r'actions/(checkout|setup-python)@[0-9a-f]{40}', s['uses'])
    upload = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/upload-artifact@'))
    assert upload['with']['if-no-files-found'] == 'error'
