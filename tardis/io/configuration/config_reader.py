import copy
import logging
import pprint
from pathlib import Path

import pandas as pd
import yaml
from astropy import units as u

from tardis.io.hdf_writer_mixin import HDFWriterMixin
from tardis.io.configuration import config_validator
from tardis.io.model.readers.csvy import load_yaml_from_csvy
from tardis.io.util import YAMLLoader, yaml_load_file

pp = pprint.PrettyPrinter(indent=4)

logger = logging.getLogger(__name__)


class ConfigurationError(ValueError):
    pass


class ConfigurationNameSpace(dict):
    """
    The configuration name space class allows to wrap a dictionary and adds
    utility functions for easy access. Accesses like a.b.c are then possible

    Code from http://goo.gl/KIaq8I

    Parameters
    ----------
    config_dict : dict
        configuration dictionary

    Returns
    -------
    config_ns : ConfigurationNameSpace
    """

    @classmethod
    def from_yaml(cls, fname):
        """
        Read a configuration from a YAML file

        Parameters
        ----------
        fname : str
            filename or path
        """
        try:
            yaml_dict = yaml_load_file(fname)
        except OSError as e:
            logger.critical(f"No config file named: {fname}")
            raise e

        return cls.from_config_dict(yaml_dict)

    @classmethod
    def from_config_dict(cls, config_dict):
        """
        Validating a config file.

        Parameters
        ----------
        config_dict : dict
            dictionary of a raw unvalidated config file

        Returns
        -------
        `tardis.config_reader.Configuration`
        """
        return cls(config_validator.validate_dict(config_dict))

    def __init__(self, value=None):
        if value is None:
            pass
        elif isinstance(value, dict):
            for key in value:
                self.__setitem__(key, value[key])
        else:
            raise TypeError("expected dict")

        if hasattr(self, "csvy_model") and hasattr(self, "model"):
            raise ValueError(
                "Cannot specify both model and csvy_model in main config file."
            )
        if hasattr(self, "csvy_model"):
            model = {}
            csvy_model_path = Path(self.config_dirname) / self.csvy_model
            csvy_yml = load_yaml_from_csvy(csvy_model_path)
            if "v_inner_boundary" in csvy_yml:
                model["v_inner_boundary"] = csvy_yml["v_inner_boundary"]
            if "v_outer_boundary" in csvy_yml:
                model["v_outer_boundary"] = csvy_yml["v_outer_boundary"]

            self.__setitem__("model", model)
            for key in self.model:
                self.model.__setitem__(key, self.model[key])

    def __setitem__(self, key, value):
        if isinstance(value, dict) and not isinstance(
            value, ConfigurationNameSpace
        ):
            value = ConfigurationNameSpace(value)

        if key in self and hasattr(self[key], "unit"):
            value = u.Quantity(value, self[key].unit)

        dict.__setitem__(self, key, value)

    def __getitem__(self, key):
        return super().__getitem__(key)

    def __getattr__(self, item):
        if item in self:
            return self[item]
        else:
            super().__getattribute__(item)

    __setattr__ = __setitem__

    def __dir__(self):
        return self.keys()

    def get_config_item(self, config_item_string):
        """
        Get configuration items using a string of type 'a.b.param'

        Parameters
        ----------
        config_item_string : str
            string of shape 'section1.sectionb.param1'
        """
        config_item_path = config_item_string.split(".")

        if len(config_item_path) == 1:
            config_item = config_item_path[0]

            if config_item.startswith("item"):
                return self[config_item_path[0]]
            else:
                return self[config_item]
        elif len(config_item_path) == 2 and config_item_path[1].startswith(
            "item"
        ):
            return self[config_item_path[0]][
                int(config_item_path[1].replace("item", ""))
            ]

        else:
            return self[config_item_path[0]].get_config_item(
                ".".join(config_item_path[1:])
            )

    def set_config_item(self, config_item_string, value):
        """
        set configuration items using a string of type 'a.b.param'

        Parameters
        ----------
        config_item_string : str
            string of shape 'section1.sectionb.param1'
        value :
            value to set the parameter with it
        """
        config_item_path = config_item_string.split(".")
        if len(config_item_path) == 1:
            self[config_item_path[0]] = value
        elif len(config_item_path) == 2 and config_item_path[1].startswith(
            "item"
        ):
            current_value = self[config_item_path[0]][
                int(config_item_path[1].replace("item", ""))
            ]
            if hasattr(current_value, "unit"):
                self[config_item_path[0]][
                    int(config_item_path[1].replace("item", ""))
                ] = u.Quantity(value, current_value.unit)
            else:
                self[config_item_path[0]][
                    int(config_item_path[1].replace("item", ""))
                ] = value

        else:
            self[config_item_path[0]].set_config_item(
                ".".join(config_item_path[1:]), value
            )

    def deepcopy(self):
        return ConfigurationNameSpace(copy.deepcopy(dict(self)))


class ConfigWriterMixin(HDFWriterMixin):
    """
    Overrides HDFWriterMixin to obtain HDF properties from configuration keys
    """

    def get_properties(self):
        data = yaml.dump(self)
        data = pd.DataFrame(index=[0], data={"config": data})
        return data


class Configuration(ConfigurationNameSpace, ConfigWriterMixin):
    """
    Tardis configuration class
    """

    hdf_name = "simulation"

    @classmethod
    def from_yaml(cls, fname, *args, **kwargs):
        try:
            yaml_dict = yaml_load_file(
                fname, loader=kwargs.pop("loader", YAMLLoader)
            )
        except OSError as e:
            logger.critical(f"No config file named: {fname}")
            raise e

        tardis_config_version = yaml_dict.get("tardis_config_version", None)
        if tardis_config_version != "v1.0":
            raise ConfigurationError(
                "Currently only tardis_config_version v1.0 supported"
            )

        kwargs["config_dirname"] = str(Path(fname).parent)

        return cls.from_config_dict(yaml_dict, *args, **kwargs)

    @classmethod
    def from_config_dict(cls, config_dict, validate=True, config_dirname=""):
        """
        Validating and subsequently parsing a config file.

        Parameters
        ----------
        config_dict : dict
            dictionary of a raw unvalidated config file
        validate : bool
            Turn validation on or off.

        Returns
        -------
        `tardis.config_reader.Configuration`
        """
        if validate:
            validated_config_dict = config_validator.validate_dict(config_dict)
        else:
            validated_config_dict = config_dict

        validated_config_dict["config_dirname"] = config_dirname

        montecarlo_section = validated_config_dict["montecarlo"]
        Configuration.validate_montecarlo_section(montecarlo_section)

        if "csvy_model" in validated_config_dict.keys():
            pass
        elif "model" in validated_config_dict.keys():
            model_section = validated_config_dict["model"]
            Configuration.validate_model_section(model_section)
            # SuperNova Section Validation
            supernova_section = validated_config_dict["supernova"]

            time_explosion = supernova_section["time_explosion"]
            luminosity_wavelength_start = supernova_section[
                "luminosity_wavelength_start"
            ]
            luminosity_wavelength_end = supernova_section[
                "luminosity_wavelength_end"
            ]
            if time_explosion.value <= 0:
                raise ValueError(
                    f"Time Of Explosion is Invalid, {time_explosion}"
                )
            if (
                luminosity_wavelength_start.value
                > luminosity_wavelength_end.value
            ):
                raise ValueError(
                    "Integral Limits for Luminosity Wavelength are Invalid, Start Limit > End Limit \n"
                    f"Luminosity Wavelength Start : {luminosity_wavelength_start} \n"
                    f"Luminosity Wavelength End : {luminosity_wavelength_end}"
                )

            # Plasma Section Validation
            plasma_section = validated_config_dict["plasma"]

            initial_t_inner = plasma_section["initial_t_inner"]
            initial_t_rad = plasma_section["initial_t_rad"]
            if initial_t_inner.value < -1:
                raise ValueError(
                    f"Initial Temperature of Inner Boundary Black Body is Invalid, {initial_t_inner}"
                )
            if initial_t_rad.value < -1:
                raise ValueError(
                    f"Initial Radiative Temperature is Invalid, {initial_t_rad}"
                )

        spectrum_section = validated_config_dict["spectrum"]
        Configuration.validate_spectrum_section(
            spectrum_section, montecarlo_section["enable_full_relativity"]
        )

        return cls(validated_config_dict)

    @staticmethod
    def validate_spectrum_section(
        spectrum_section, enable_full_relativity=False
    ):
        """
        Validate the spectrum section dictionary

        Parameters
        ----------
        spectrum_section : dict
        """
        # Spectrum Section Validation

        start = spectrum_section["start"]
        stop = spectrum_section["stop"]
        if start.value > stop.value:
            raise ValueError(
                "Start Value of Spectrum Cannot be Greater than Stop Value. \n"
                f"Start : {start} \n"
                f"Stop : {stop}"
            )

        spectrum_integrated = spectrum_section["method"] == "integrated"
        if enable_full_relativity and spectrum_integrated:
            raise NotImplementedError(
                "The spectrum method is set to 'integrated' and "
                "enable_full_relativity to 'True'.\n"
                "The FormalIntegrator is not yet implemented for the full "
                "relativity mode. "
            )

    @staticmethod
    def validate_model_section(model_section):
        """
        Parse the model section dictionary

        Parameters
        ----------
        model_section : dict
        """
        if model_section["structure"]["type"] == "specific":
            start_velocity = model_section["structure"]["velocity"]["start"]
            stop_velocity = model_section["structure"]["velocity"]["stop"]
            if stop_velocity.value < start_velocity.value:
                raise ValueError(
                    "Stop Velocity Cannot Be Less than Start Velocity. \n"
                    f"Start Velocity = {start_velocity} \n"
                    f"Stop Velocity = {stop_velocity}"
                )
        elif model_section["structure"]["type"] == "file":
            v_inner_boundary = model_section["structure"]["v_inner_boundary"]
            v_outer_boundary = model_section["structure"]["v_outer_boundary"]
            if v_outer_boundary.value < v_inner_boundary.value:
                raise ValueError(
                    "Outer Boundary Velocity Cannot Be Less than Inner Boundary Velocity. \n"
                    f"Inner Boundary Velocity = {v_inner_boundary} \n"
                    f"Outer Boundary Velocity = {v_outer_boundary}"
                )
        if "density" in model_section["structure"].keys():
            if model_section["structure"]["density"]["type"] == "exponential":
                rho_0 = model_section["structure"]["density"]["rho_0"]
                v_0 = model_section["structure"]["density"]["v_0"]
                if rho_0.value <= 0:
                    raise ValueError(f"Density Specified is Invalid, {rho_0}")
                if v_0.value <= 0:
                    raise ValueError(f"Velocity Specified is Invalid, {v_0}")
                if "time_0" in model_section["structure"]["density"].keys():
                    time_0 = model_section["structure"]["density"]["time_0"]
                    if time_0.value <= 0:
                        raise ValueError(f"Time Specified is Invalid, {time_0}")
            elif model_section["structure"]["density"]["type"] == "power_law":
                rho_0 = model_section["structure"]["density"]["rho_0"]
                v_0 = model_section["structure"]["density"]["v_0"]
                if rho_0.value <= 0:
                    raise ValueError(f"Density Specified is Invalid, {rho_0}")
                if v_0.value <= 0:
                    raise ValueError(f"Velocity Specified is Invalid, {v_0}")
                if "time_0" in model_section["structure"]["density"].keys():
                    time_0 = model_section["structure"]["density"]["time_0"]
                    if time_0.value <= 0:
                        raise ValueError(f"Time Specified is Invalid, {time_0}")
            elif model_section["structure"]["density"]["type"] == "uniform":
                density = model_section["structure"]["density"]["value"]
                if density.value <= 0:
                    raise ValueError(
                        f"Density Value Specified is Invalid, {density}"
                    )
                if "time_0" in model_section["structure"]["density"].keys():
                    time_0 = model_section["structure"]["density"]["time_0"]
                    if time_0.value <= 0:
                        raise ValueError(f"Time Specified is Invalid, {time_0}")

    @staticmethod
    def validate_montecarlo_section(montecarlo_section):
        """
        Validate the montecarlo section dictionary

        Parameters
        ----------
        montecarlo_section : dict
        """
        if montecarlo_section["convergence_strategy"]["type"] == "damped":
            montecarlo_section[
                "convergence_strategy"
            ] = Configuration.parse_convergence_section(
                montecarlo_section["convergence_strategy"]
            )
        elif montecarlo_section["convergence_strategy"]["type"] == "custom":
            raise NotImplementedError(
                'convergence_strategy is set to "custom"; '
                "you need to implement your specific convergence treatment"
            )
        else:
            raise ValueError('convergence_strategy is not "damped" or "custom"')

    @staticmethod
    def parse_convergence_section(convergence_section_dict):
        """
        Parse the convergence section dictionary

        Parameters
        ----------
        convergence_section_dict : dict
            dictionary
        """
        convergence_parameters = ["damping_constant", "threshold", "type"]

        for convergence_variable in ["t_inner", "t_rad", "w", "v_inner_boundary"]:
            if convergence_variable not in convergence_section_dict:
                convergence_section_dict[convergence_variable] = {}
            convergence_variable_section = convergence_section_dict[
                convergence_variable
            ]
            for param in convergence_parameters:
                if convergence_variable_section.get(param, None) is None:
                    if param in convergence_section_dict:
                        convergence_section_dict[convergence_variable][
                            param
                        ] = convergence_section_dict[param]

        return convergence_section_dict

    def __init__(self, config_dict):
        super().__init__(config_dict)


def quantity_representer(dumper, data):
    """
    Represents Astropy Quantity as str

    Parameters
    ----------
    dumper :
        YAML dumper object
    data :
        ConfigurationNameSpace object

    Returns
    -------
    yaml dumper representation of Quantity as string
    """
    return dumper.represent_data(str(data))


def cns_representer(dumper, data):
    """
    Represents Configuration as dict

    Parameters
    ----------
    dumper :
        YAML dumper object
    data :
        ConfigurationNameSpace object

    Returns
    -------
    yaml dumper representation of Configuration as dict
    """
    return dumper.represent_dict(dict(data))


yaml.add_representer(u.Quantity, quantity_representer)
yaml.add_representer(ConfigurationNameSpace, cns_representer)
yaml.add_representer(Configuration, cns_representer)
