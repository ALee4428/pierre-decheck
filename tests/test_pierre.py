import os

import json
from flask_api.status import HTTP_200_OK

from lib.payloads import PR_COMMENT_EVENT, PR_CREATED, ISSUE_DETAIL
from lib.pierre import (
    get_bodies,
    get_dependencies_from_bodies,
    is_external_dependency,
    get_external_owner_and_repo,
    get_owner_and_repo,
    BASE_GITHUB_URL,
    check,
    HEADERS,
    get_dependency_state,
)

from mock import patch, Mock

GITHUB_HEADERS = {
    "X-GitHub-Event": "issue_comment",
    "X-GitHub-Delivery": "foo",
    "User-Agent": "GitHub-Foo"
}

HOST = "infinite-harbor-38537.herokuapp.com"


class TestPierre(object):

    def test_get_bodies_from_pr_comment_event(self):
        bodies = get_bodies(json.loads(PR_COMMENT_EVENT))

        assert 2 == len(bodies)
        assert "This is the PR body" == bodies[0]
        assert "this is a comment" == bodies[1]

    def test_get_bodies_from_pr_created_event(self):
        bodies = get_bodies(json.loads(PR_CREATED))

        assert 1 == len(bodies)
        assert "This is the PR body" == bodies[0]

    def test_get_dependencies_identifiers_from_list(self):
        bodies = ["Depends on #2", "", "depends on #3", "No dependencies here", "depends on #4"]

        root_id = '4'
        dependencies = get_dependencies_from_bodies(bodies, root_id)

        assert 2 == len(dependencies)
        assert "2" in dependencies
        assert "3" in dependencies

    def test_get_dependencies_identifiers_from_single_body(self):
        bodies = ["Depends on #2. Depends on #3"]

        root_id = '4'
        dependencies = get_dependencies_from_bodies(bodies, root_id)

        assert 2 == len(dependencies)
        assert "2" in dependencies
        assert "3" in dependencies

    def test_get_dependencies_removes_duplicates(self):
        bodies = ["Depends on #2", "", "depends on #3", "depends on #3"]

        root_id = '4'
        dependencies = get_dependencies_from_bodies(bodies, root_id)

        assert 2 == len(dependencies)

    def test_get_dependencies_accepts_external_dependencies(self):
        bodies = ["Depends on #2", "", "depends on alvarocavalcanti/my-dev-templates#1"]

        root_id = '4'
        dependencies = get_dependencies_from_bodies(bodies, root_id)

        assert 2 == len(dependencies)
        assert "2" in dependencies
        assert "alvarocavalcanti/my-dev-templates#1" in dependencies

    def test_is_external_dependency(self):
        assert is_external_dependency("alvarocavalcanti/my-dev-templates#1")
        assert not is_external_dependency("1")

    def test_get_external_owner_and_repo(self):
        owner, repo, dependency_id = get_external_owner_and_repo("alvarocavalcanti/my-dev-templates#1")

        assert "alvarocavalcanti" == owner
        assert "my-dev-templates" == repo
        assert "1" == dependency_id

    def test_get_owner_and_repo_from_pr_comment_event(self):
        owner, repo = get_owner_and_repo(json.loads(PR_COMMENT_EVENT))

        assert "alvarocavalcanti" == owner
        assert "pierre-decheck" == repo

    def test_get_owner_and_repo_from_pr_created_event(self):
        owner, repo = get_owner_and_repo(json.loads(PR_CREATED))

        assert "alvarocavalcanti" == owner
        assert "pierre-decheck" == repo

    @patch('lib.pierre.requests.request')
    def test_checks_dependencies_upon_receiving_pr_created_event(self, requests_mock):
        payload = json.loads(PR_CREATED.replace("This is the PR body", "This is the PR body. Depends on #2."))

        response = check(payload, headers=GITHUB_HEADERS, host=HOST)

        assert 201 == response.get("statusCode")

        expected_url = "{}repos/{}/{}/issues/{}".format(
            BASE_GITHUB_URL,
            "alvarocavalcanti",
            "pierre-decheck",
            "2"
        )

        requests_mock.assert_any_call('GET', expected_url, headers=HEADERS)

    @patch('lib.pierre.requests.request')
    def test_checks_dependencies_upon_receiving_pr_comment_event_for_more_than_one_dependency(
            self, requests_mock
    ):
        payload = PR_COMMENT_EVENT.replace("This is the PR body", "Depends on #2.")
        payload = json.loads(payload.replace("this is a comment", "Depends on #3."))

        response = check(payload, headers=GITHUB_HEADERS, host=HOST)

        assert 201 == response.get("statusCode")

        expected_url_dep_2 = "{}repos/{}/{}/issues/{}".format(
            BASE_GITHUB_URL,
            "alvarocavalcanti",
            "pierre-decheck",
            "2"
        )

        expected_url_dep_3 = "{}repos/{}/{}/issues/{}".format(
            BASE_GITHUB_URL,
            "alvarocavalcanti",
            "pierre-decheck",
            "3"
        )

        requests_mock.assert_any_call('GET', expected_url_dep_2, headers=HEADERS)
        requests_mock.assert_any_call('GET', expected_url_dep_3, headers=HEADERS)

    @patch("requests.request")
    @patch.dict(os.environ, {'RELEASE_LABEL': 'RELEASED'})
    def test_gets_dependency_state_as_open_when_issue_is_closed_but_has_not_been_released(self, mock_request):
        request_response = Mock()
        request_response.status_code = HTTP_200_OK
        issue_detail = ISSUE_DETAIL.replace("ISSUE_STATUS", "closed")
        request_response.text = issue_detail

        mock_request.return_value = request_response

        issue_state = get_dependency_state("1", "foo", "bar")

        assert "closed-not-released" == issue_state

    @patch("requests.request")
    @patch.dict(os.environ, {'RELEASE_LABEL': 'RELEASED'})
    def test_gets_dependency_state_as_closed_when_issue_is_closed_and_has_been_released(self, mock_request):
        request_response = Mock()
        request_response.status_code = HTTP_200_OK
        issue_detail = ISSUE_DETAIL.replace("ISSUE_STATUS", "closed")
        issue_detail = issue_detail.replace("LABEL_DESCRIPTION", "RELEASED")
        request_response.text = issue_detail

        mock_request.return_value = request_response

        issue_state = get_dependency_state("1", "foo", "bar")

        assert "closed" == issue_state
