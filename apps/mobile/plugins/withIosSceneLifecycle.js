const { withAppDelegate, withInfoPlist } = require("expo/config-plugins");

module.exports = function withIosSceneLifecycle(config) {
  config = withInfoPlist(config, (config) => {
    config.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: "Default Configuration",
            UISceneDelegateClassName: "$(PRODUCT_MODULE_NAME).SceneDelegate",
          },
        ],
      },
    };
    return config;
  });

  return withAppDelegate(config, (config) => {
    const appDelegate = config.modResults;
    const legacyDelegate = "class AppDelegate: ExpoAppDelegate {";
    const sceneFactoryProvider = "class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {";
    const sceneDelegate = "class SceneDelegate: ExpoAppSceneDelegate {}";
    const reactDelegate = "class ReactNativeDelegate: ExpoReactNativeFactoryDelegate";
    if (
      appDelegate.contents.includes(sceneFactoryProvider) &&
      appDelegate.contents.includes(sceneDelegate)
    ) return config;

    const legacyWindow = /^#if os\(iOS\) \|\| os\(tvOS\)\n    window = UIWindow[^\n]*\n    factory\.startReactNative\([\s\S]*?\n#endif\n\n/m;
    if (
      appDelegate.language !== "swift" ||
      !appDelegate.contents.includes(legacyDelegate) ||
      !appDelegate.contents.includes(reactDelegate) ||
      !legacyWindow.test(appDelegate.contents)
    ) {
      throw new Error("Cannot apply UIScene migration to this Expo AppDelegate template.");
    }

    appDelegate.contents = appDelegate.contents
      .replace(legacyDelegate, sceneFactoryProvider)
      .replace(legacyWindow, "")
      .replace(reactDelegate, `${sceneDelegate}\n\n${reactDelegate}`);
    return config;
  });
};
