"""Test inven_api/common/config.py classes and functions."""
# Standard Library
from random import choice
from string import ascii_letters
from string import ascii_lowercase
import tempfile

# External Party
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
import pytest

# Local Modules
from inven_api.common.config import CaseInsensitiveDict
from inven_api.common.config import EnvConfig
from inven_api.common.config import InvalidCaseInsenstiveKeyError

ASCII_TEXT_ST = st.text(alphabet=ascii_letters)
ASCII_LOWERTEXT_ST = st.text(alphabet=ascii_lowercase)
ALL_CASE_FUNCS = [str.lower, str.capitalize, str.upper, lambda x: x]


# custom strategies that yields a dict
@st.composite
def ci_unique_dict(draw):
    data = draw(st.dictionaries(ASCII_LOWERTEXT_ST, ASCII_TEXT_ST))
    return {
        "".join([choice(ALL_CASE_FUNCS)(c) for c in key]): value
        for key, value in data.items()
    }


@pytest.fixture(scope="session")
def example_data() -> dict:
    return {"FOO": "BAR", "BAZ": "BIFF"}


@pytest.fixture(scope="session")
def example_config_file(example_data: dict) -> str:
    with tempfile.NamedTemporaryFile(mode="w+") as file:
        file.writelines([f"{key}={value}\n" for key, value in example_data.items()])
        file.flush()
        yield file.name  # type: ignore


class TestCaseInsensDictUnit:
    _case_funcs = ALL_CASE_FUNCS

    @pytest.fixture()
    def empty_caseinsens(self) -> CaseInsensitiveDict:
        return CaseInsensitiveDict()

    @pytest.fixture()
    def example_caseinsens(self, example_data: dict) -> CaseInsensitiveDict:
        return CaseInsensitiveDict(example_data)

    @classmethod
    def check_all_cases_contained(cls, data: dict) -> bool:
        return all(
            data[func(key)] == data[key] for key in data for func in cls._case_funcs
        )

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(ASCII_TEXT_ST, st.one_of(ASCII_TEXT_ST, st.integers()))
    def test_empty_dict(
        self,
        empty_caseinsens: CaseInsensitiveDict,
        non_existent_key: str,
        default_value: str | int,
    ):
        assert len(empty_caseinsens) == 0
        with pytest.raises(KeyError):
            empty_caseinsens[non_existent_key]
        assert empty_caseinsens.get(non_existent_key) is None
        assert empty_caseinsens.get(non_existent_key, default_value) is default_value
        assert len(empty_caseinsens.keys()) == 0
        assert len(empty_caseinsens.values()) == 0
        assert len(empty_caseinsens.items()) == 0

    @given(ASCII_TEXT_ST, ASCII_TEXT_ST)
    def test_set_item(self, given_key: str, given_val: str):
        cd = CaseInsensitiveDict()
        cd[given_key] = given_val
        assert len(cd) == 1
        assert self.check_all_cases_contained(cd)  # type: ignore
        assert len(cd.keys()) == 1
        assert len(cd.values()) == 1
        assert len(cd.items()) == 1
        test_key, test_val = next(iter(cd.items()))
        assert test_key is given_key
        assert test_val is given_val

    @given(st.one_of(st.integers(), st.complex_numbers(), st.floats()))
    def test_dict_key_modifier(self, random_key: int | complex | float):
        with pytest.raises(InvalidCaseInsenstiveKeyError, match="Key"):
            CaseInsensitiveDict._key_modifier(random_key)

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(ci_unique_dict())
    def test_update(self, empty_caseinsens: CaseInsensitiveDict, update_data: dict):
        # clear the empty dict due to how Hypothesis treats function fixtures
        empty_caseinsens.clear()
        assert len(empty_caseinsens) == 0
        empty_caseinsens.update(update_data)
        assert len(empty_caseinsens) == len(update_data)
        for key, value in update_data.items():
            for cfunc in self._case_funcs:
                assert empty_caseinsens[cfunc(key)] == value

    def test_dict_repr(self, example_caseinsens: CaseInsensitiveDict):
        # make sure the underlying tuple data not exposed
        assert "(" not in repr(example_caseinsens)
        assert ")" not in repr(example_caseinsens)
        eval_d: dict = eval(repr(example_caseinsens))
        for key, value in eval_d.items():
            assert example_caseinsens[key] == value
        # check the other way, make sure eval_d is made of original keys
        for key, value in example_caseinsens.items():
            assert eval_d[key] == value


class TestEnvConfigUnit:
    @pytest.fixture()
    def example_cfg(self, example_config_file: str) -> EnvConfig:
        return EnvConfig(example_config_file)

    @given(st.one_of(st.integers(), st.floats(), st.complex_numbers()))
    def test_cfg_bad_init(self, bad_arg: int | float | complex):
        with pytest.raises(TypeError, match="<class"):
            EnvConfig(bad_arg)  # type: ignore

    def test_get_attribute(self, example_cfg: EnvConfig, example_data: dict):
        print(example_cfg.config)
        for key, value in example_data.items():
            for cfunc in ALL_CASE_FUNCS:
                assert eval(f"example_cfg.{cfunc(key)}") == value
                assert getattr(example_cfg, cfunc(key)) == value

    def test_private_config(self, example_cfg: EnvConfig, example_data: dict):
        cfg_repr = repr(example_cfg)
        for key, value in example_data.items():
            assert key not in cfg_repr
            assert value not in cfg_repr
        assert "EnvConfig(items=2)" == cfg_repr
        # shouldn't leak the details in str call either
        assert str(example_cfg) == cfg_repr

    @given(ASCII_TEXT_ST)
    def test_not_real_file(self, fake_file: str):
        with pytest.raises(FileNotFoundError, match=fake_file):
            EnvConfig(fake_file)
