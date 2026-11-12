cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.10"
  sha256 arm:   "87d1bb496ca0defd8ab5ddaf7f0285c97d3081af58f5f1f4a2665df111e95510",
         intel: "36602bc53467c81ead743f2b485d8afcafdd8f6df4753de92c2f02a8388cf20a"

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
