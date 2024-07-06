$(function () {
    function OctolightViewModel(parameters) {
        var self = this;

        self.settingsViewModel = parameters[0]
        self.loginState = parameters[1];

        self.light_indicator = $("#light_indicator");
        self.isLightOn = ko.observable(undefined);

        self.onBeforeBinding = function () {
            self.settings = self.settingsViewModel.settings;
        };

        self.onDataUpdaterPluginMessage = function (plugin, data) {
            if (plugin != "octolight")
                return;

            if (data.isLightOn !== undefined)
                self.isLightOn(data.isLightOn);
        };

        self.onStartup = function () {
            self.isLightOn.subscribe(function () {
                if (self.isLightOn()) {
                    self.light_indicator.removeClass("off").addClass("on");
                } else {
                    self.light_indicator.removeClass("on").addClass("off");
                }
            });
        };

        self.light_toggle = function() {
           $.ajax({
                url: API_BASEURL + "plugin/octolight",
                type: "POST",
                dataType: "json",
                data: JSON.stringify({
                    command: "toggle"
                }),
                contentType: "application/json; charset=UTF-8"
            })
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: OctolightViewModel,
        dependencies: ["settingsViewModel", "loginStateViewModel"],
        elements: ["#navbar_plugin_octolight", "#settings_plugin_octolight"]
    });
});
