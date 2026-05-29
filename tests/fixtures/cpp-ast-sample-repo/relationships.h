#pragma once

#include <memory>
#include <string>

namespace audio {

class AudioBuffer;
class MidiMessage;

typedef int SampleCount;
using SampleRate = double;

class AudioProcessor {
public:
    virtual void processBlock(AudioBuffer* buffer, int numSamples) = 0;
    virtual void handleMidi(MidiMessage& msg) = 0;
    virtual ~AudioProcessor() = default;

protected:
    int sampleRate_;
};

class PluginProcessor : public AudioProcessor {
    friend class PluginEditor;

public:
    void processBlock(AudioBuffer* buffer, int numSamples) override;
    void handleMidi(MidiMessage& msg) override;
    AudioBuffer* getOutput() const;

private:
    float gain_;
};

class PluginEditor {
public:
    explicit PluginEditor(PluginProcessor* processor);
    void paint();

    class ToolBar {
    public:
        void refresh();
    };

private:
    PluginProcessor* processor_;
};

class AudioBuffer {
public:
    float* getData();
    int getNumSamples() const;

private:
    float* data_;
    int numSamples_;
};

class MidiMessage {
public:
    int getNote() const;
    int getVelocity() const;

private:
    int note_;
    int velocity_;
};

}  // namespace audio
