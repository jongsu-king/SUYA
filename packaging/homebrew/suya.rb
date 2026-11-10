cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.5"
  sha256 arm:   "857429af6c37a2d5cdc5d2c6438bb31aa31fb351f834a696d4eb93b8ef7571a7",
         intel: "b859a39e1f0f3c2b4ce5c631a4e5f6d1a40e05e58997841940c11f13d8ea1c65"

  url "https://github.com/jongsu-king/SUYA/releases/download/v#{version}/SUYA-#{version}-macos-#{arch}.dmg"
  name "SUYA"
  desc "Collects Antarctic ocean temperature, salinity and air temperature"
  homepage "https://github.com/jongsu-king/SUYA"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: :monterey

  app "SUYA.app"

  zap trash: [
    "~/Library/Application Support/SUYA",
    "~/Library/Preferences/com.suya.monitor.plist",
    "~/Library/Saved Application State/com.suya.monitor.savedState",
  ]
end
