#pragma once

#include <memory>
#include <string>

// Connected classes — should NOT be flagged as dormant
namespace engine {

class Config {
public:
    int getValue() const;
private:
    int value_;
};

class Logger {
public:
    void log(const std::string& msg);
};

class Engine {
public:
    void run(Config& cfg);
    Logger* getLogger() const;

private:
    std::unique_ptr<Logger> logger_;
    Config config_;
};

class PluginBase {
public:
    virtual void process() = 0;
    virtual ~PluginBase() = default;
};

class AudioPlugin : public PluginBase {
public:
    void process() override;

private:
    float gain_;
};

class MidiPlugin : public PluginBase {
    friend class PluginInspector;

public:
    void process() override;

private:
    int channel_;
};

class PluginInspector {
public:
    void inspect(PluginBase* plugin);
};

class Editor {
public:
    explicit Editor(Engine* engine);

    class ToolBar {
    public:
        void refresh();
    };

private:
    Engine* engine_;
};

}  // namespace engine

// Orphan classes — SHOULD be flagged as dormant
// These have no inheritance, field refs, param refs, friend refs, or nesting

class OrphanHelperA {
public:
    void doWork();
private:
    int data_;
};

class OrphanHelperB {
public:
    std::string describe() const;
private:
    std::string label_;
};

// ownership-transfer
class FrameworkView {
public:
    void draw();
private:
    int width_;
};
