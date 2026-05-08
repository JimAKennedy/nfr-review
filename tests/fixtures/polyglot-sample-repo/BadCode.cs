using System;
using System.Threading.Tasks;

namespace PolyglotFixture
{
    public class BadCode
    {
        public void SwallowException()
        {
            try
            {
                int.Parse("abc");
            }
            catch (Exception)
            {
                // broad catch without rethrow
            }
        }

        public void LogToConsole(string message)
        {
            Console.WriteLine("DEBUG: " + message);
        }

        public async void FireAndForget()
        {
            await Task.Delay(100);
        }

        public string BlockOnAsync()
        {
            var result = Task.Run(() => "hello").Result;
            return result;
        }
    }
}
