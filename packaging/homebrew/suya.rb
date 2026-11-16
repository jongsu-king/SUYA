cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.12"
  sha256 arm:   "23f66b460fcf9974768d99da94368e53dd0596424439a137b7427327c647effe",
         intel: "765e8c7ea5c80b141d701273c86559ba76a8080da36cb4e188aa8903c74dc467"

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
