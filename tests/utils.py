"""Testing utilities."""
import os
from typing import Optional

import pytest

# check for cmem environment and skip if not present
from _pytest.mark import MarkDecorator
from cmem.cmempy.api import get_token
from cmem_plugin_base.dataintegration.context import (
    UserContext,
    TaskContext,
    ExecutionContext,
    ReportContext,
    PluginContext,
)

needs_cmem: MarkDecorator = pytest.mark.skipif(
    os.environ.get("CMEM_BASE_URI", "") == "", reason="Needs CMEM configuration"
)


class TestUserContext(UserContext):
    """dummy user context that can be used in tests"""

    __test__ = False

    def __init__(self):
        # get access token from default service account
        access_token = os.environ.get("OAUTH_ACCESS_TOKEN", "")
        if not access_token:
            access_token = get_token()["access_token"]
        self.token = lambda: access_token


class TestPluginContext(PluginContext):
    """dummy plugin context that can be used in tests"""

    __test__ = False

    def __init__(
        self,
        project_id: str = "dummyProject",
    ):
        self.project_id = project_id
        self.user = TestUserContext()


class TestTaskContext(TaskContext):
    """dummy Task context that can be used in tests"""

    __test__ = False

    def __init__(self, project_id: str = "dummyProject"):
        self.project_id = lambda: project_id


class TestExecutionContext(ExecutionContext):
    """dummy execution context that can be used in tests"""

    __test__ = False

    def __init__(
        self,
        project_id: str = "dummyProject",
    ):
        self.report = ReportContext()
        self.task = TestTaskContext(project_id=project_id)
        self.user = TestUserContext()
