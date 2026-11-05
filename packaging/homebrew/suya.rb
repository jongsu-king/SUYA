cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.3"
  sha256 arm:   "09c5c8fcaf9b1932bd16ea04834ad456c5fe8309e3fc09da351fe9c90937585e",
         intel: "37b2b455c7e7c8d2a1cf27d813f1c584be08ce120eb3369c9f85070cc3f6ccbf"

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
