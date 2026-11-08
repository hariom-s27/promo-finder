"""D82 filter failures: invented bodies and fake transports only."""
import json
from types import SimpleNamespace

import pytest

from promo_finder import judging
from promo_finder.llm import ContentFiltered
from promo_finder.provider_protocol import content_filter_failure, failed_request_metadata
from test_p07a import call, error, foundry_cfg, no_network
from test_llm import cfg, make_client, resp
from test_judging import Provider, client as judge_client, jcfg, setup


def blocked_body(location='choices'):
    detail = {'error': {'code': 'content_filter', 'message':
        "invented private text; label 'MultiSeverity_ViolenceScore'; invented more private text"}}
    if location == 'choices':
        return {'choices': [{'content_filter_results': detail}], 'prompt_filter_results': None}
    return {'prompt_filter_results': [{'content_filter_results': detail}]}


@pytest.mark.parametrize('location', ['choices', 'prompt'])
@pytest.mark.parametrize('status', [400, 503])
def test_nested_filter_is_logged_and_never_retried(foundry_cfg, location, status):
    failure = error(status)
    failure.body = blocked_body(location)
    c, fake, _, _ = make_client(foundry_cfg, [failure, resp('{"ok": true}')])
    c.consecutive_429s = 4
    with pytest.raises(ContentFiltered) as caught:
        call(c)
    assert caught.value.code == 'CONTENT_FILTERED'
    assert len(fake.calls) == 1 and c.calls_made == 1
    assert c.consecutive_429s == 0
    assert not list(c.cache_dir.glob('*.json'))
    failures = [r for r in c.records if r.get('event') == 'http_attempt_failed']
    assert len(failures) == 1
    assert failures[0]['error_code'] == 'CONTENT_FILTERED'
    assert failures[0]['error'] == f'HTTP_{status}'
    assert failures[0]['provider_error_code'] == 'content_filter'
    assert failures[0]['content_filter_labels'] == ['MultiSeverity_ViolenceScore']
    assert 'private text' not in c.log_path.read_text(encoding='utf-8')
    assert not any(r.get('event') in {'transport_retry','response_retry','json_mode_fallback'} for r in c.records)
    metadata = judging.failed_metadata(c, 'p07.cold_judge.invented')
    assert metadata['content_filter_labels'] == ['MultiSeverity_ViolenceScore']


def test_prompt_category_block_is_filter_failure_without_code():
    metadata = failed_request_metadata({'prompt_filter_results': [{'content_filter_results': {
        'violence': {'filtered': True, 'severity': 'high', 'message': 'invented private text'}}}]})
    assert content_filter_failure(metadata)
    assert metadata['content_filter_categories'] == {'violence': {'filtered': True, 'severity': 'high'}}
    assert 'private' not in json.dumps(metadata)


def test_nested_filter_not_hidden_by_generic_root_error_code():
    body = blocked_body()
    body['error'] = {'code': 'BadRequest'}
    metadata = failed_request_metadata(body)
    assert metadata['provider_error_code'] == 'BadRequest'
    assert metadata['content_filter_code'] == 'content_filter'
    assert content_filter_failure(metadata)


@pytest.mark.parametrize('body', [{}, {'choices': None}, {'choices': ['invented']},
    {'prompt_filter_results': 'invented'}, {'choices': [{'content_filter_results': {'error': {'code': []}}}]},
    {'prompt_filter_results': [{'content_filter_results': {'violence': {'filtered': False, 'severity': 'medium'}}}]}])
def test_malformed_or_unblocked_filter_metadata_is_not_blocking(body):
    assert not content_filter_failure(failed_request_metadata(body))


def test_only_known_label_names_can_escape_an_error_message():
    body = blocked_body()
    body['choices'][0]['content_filter_results']['error']['message'] += ' MultiSeverity_PrivateNameScore'
    metadata = failed_request_metadata(body)
    assert metadata['content_filter_labels'] == ['MultiSeverity_ViolenceScore']
    assert 'PrivateName' not in json.dumps(metadata)


def test_200_filtered_response_is_not_parsed_cached_or_retried(foundry_cfg):
    response = resp('invented private blocked output', finish='content_filter')
    response.model_dump = lambda: blocked_body()
    c, fake, _, _ = make_client(foundry_cfg, [response, resp('{"ok": true}')])
    with pytest.raises(ContentFiltered):
        call(c)
    assert len(fake.calls) == 1 and not list(c.cache_dir.glob('*.json'))
    row = next(r for r in c.records if r.get('event') == 'http_attempt_failed')
    assert row['http_status_code'] == 200 and row['error_code'] == 'CONTENT_FILTERED'
    assert 'private blocked output' not in c.log_path.read_text(encoding='utf-8')


def test_filtered_item_stays_unscored_and_skips_fidelity(jcfg, episode_factory):
    ep, _ = setup(jcfg, episode_factory)
    provider = Provider()
    original = provider.create
    def create(**kwargs):
        if 'hook_rating' in kwargs['response_format']['json_schema']['schema']['properties']:
            provider.calls.append(kwargs)
            failure = error(400)
            failure.body = blocked_body()
            raise failure
        return original(**kwargs)
    provider.chat.completions.create = create
    c = judge_client(jcfg, provider)
    result = judging.run(jcfg, [ep], c)
    items = json.loads((jcfg.output_root/'judge/judge_E05.json').read_text(encoding='utf-8'))['items']
    item = items[0]
    assert all(r['error_code'] == 'CONTENT_FILTERED' for r in item['runs'])
    assert item['aggregate']['successful_runs'] == 0
    assert item['fidelity']['status'] == 'skipped'
    assert len(provider.calls) == 4  # key and three declared samples; no retry
    assert result['failed_runs_by_part']['cold_judge'] == 3
