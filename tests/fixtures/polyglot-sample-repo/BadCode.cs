using System;

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
    }
}
