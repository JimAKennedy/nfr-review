using System;
using System.Threading.Tasks;

namespace SampleApp
{
    public class BadAsync
    {
        public async void FireAndForget()
        {
            await Task.Delay(100);
        }

        public async void AnotherAsyncVoid()
        {
            await DoWorkAsync();
        }

        public async Task<int> MissingConfigureAwait()
        {
            await Task.Delay(100);
            return 42;
        }

        public async Task<int> WithConfigureAwait()
        {
            await Task.Delay(100).ConfigureAwait(false);
            return 42;
        }

        public int BlockingResult()
        {
            return Task.Run(() => 42).Result;
        }

        public void BlockingWait()
        {
            Task.Run(() => DoWork()).Wait();
        }

        public int BlockingGetAwaiter()
        {
            return Task.Run(() => 42).GetAwaiter().GetResult();
        }

        public async Task<string> GoodAsync()
        {
            var result = await DoWorkAsync().ConfigureAwait(false);
            return result.ToString();
        }

        private Task<int> DoWorkAsync() => Task.FromResult(1);
        private void DoWork() { }
    }
}
