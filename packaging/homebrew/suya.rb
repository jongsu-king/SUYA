cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.11"
  sha256 arm:   "d484f1e2aaef37af842d8447fd243928e1d7422ddf2e960f02e7e9f6d7b9aaef",
         intel: "301b2467553c4b571b0493bbebec1a4e70401ed47be72c2edddbe2e1a2ed1438"

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
